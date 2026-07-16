"""Application orchestration (PRD §5, §11): single process wiring the collector
loop, the tray, and lifecycle control. The FastAPI server is added in Phase 3;
until then ``Open Dashboard`` simply points the browser at the localhost URL.

Threading model: pystray's icon runs on the main thread (blocking); the
collector runs on a supervised background thread that restarts on crash.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time

from . import autostart, config as configmod, db as dbmod, desktop, tray
from .collector import idle as idlemod, parsers
from .collector.sampler import ForegroundSampler
from .collector.spans import SpanBuilder
from .collector.stopwatch import StopwatchReader
from .log import RateLimitedLog, get
from .rules.engine import RulesEngine
from .runtime import RuntimeState
from .singleton import SingleInstance
from .timeutil import day_bounds, local_day, now_ts

_log = get("app")


# --- controller --------------------------------------------------------------
class Controller:
    """Shared lifecycle state + the callbacks the tray menu invokes."""

    def __init__(self, cfg: configmod.Config):
        self.cfg = cfg
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.icon = None                       # set after tray.build
        self.scheduler = None                  # set after Scheduler.start (Phase 4)
        self._timer: threading.Timer | None = None

    # tray callbacks -------------------------------------------------------
    def is_paused(self) -> bool:
        return self.pause_event.is_set()

    def pause(self, minutes: int | None) -> None:
        self._cancel_timer()
        self.pause_event.set()
        self._refresh_icon()
        secs = self._seconds_to_day_end() if minutes is None else minutes * 60
        self._timer = threading.Timer(secs, self.resume)
        self._timer.daemon = True
        self._timer.start()
        _log.info("tracking paused for %s", "rest of day" if minutes is None else f"{minutes}m")

    def resume(self) -> None:
        self._cancel_timer()
        self.pause_event.clear()
        self._refresh_icon()
        _log.info("tracking resumed")

    def open_dashboard(self) -> None:
        host = self.cfg.get("server", "host", "127.0.0.1")
        port = self.cfg.get("server", "port", 8756)
        app_window = bool(self.cfg.get("server", "app_window", True))
        desktop.open_dashboard(f"http://{host}:{port}", app_window=app_window)

    def summarize_now(self) -> None:
        """On-demand daily journal (tray → 'Summarize now', §11). Runs off the
        tray thread so the menu never blocks."""
        def _run() -> None:
            conn = dbmod.connect()
            try:
                from .ai import jobs
                from .ai.groq_client import GroqClient
                date = local_day(now_ts(), self.cfg.timezone, self.cfg.day_start_hour)
                jobs.summarize_day(conn, GroqClient(self.cfg), self.cfg, date, force=True)
                _log.info("summarize-now complete for %s", date)
            except Exception as e:  # noqa: BLE001
                _log.warning("summarize-now failed: %s", e)
            finally:
                conn.close()
        threading.Thread(target=_run, name="summarize-now", daemon=True).start()

    def autostart_enabled(self) -> bool:
        return autostart.enabled()

    def toggle_autostart(self) -> None:
        (autostart.disable if autostart.enabled() else autostart.enable)()

    def quit(self) -> None:
        _log.info("quit requested")
        self._cancel_timer()
        self.stop_event.set()
        if self.icon is not None:
            self.icon.stop()

    # helpers --------------------------------------------------------------
    def _cancel_timer(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _refresh_icon(self) -> None:
        if self.icon is not None:
            paused = self.is_paused()
            self.icon.icon = tray.make_image(paused)
            self.icon.title = "Sanjaya — paused" if paused else "Sanjaya"

    def _seconds_to_day_end(self) -> float:
        now = now_ts()
        tz, dsh = self.cfg.timezone, self.cfg.day_start_hour
        _start, end = day_bounds(local_day(now, tz, dsh), tz, dsh)
        return max(60.0, end - now)


# --- collector loop ----------------------------------------------------------
def _make_enqueue_unknown(conn: sqlite3.Connection):
    def enqueue(span: dict) -> None:
        try:
            conn.execute(
                "INSERT INTO ai_queue(kind, payload, created_ts) VALUES('classify', ?, ?)",
                (json.dumps({"span_id": span.get("_id")}), now_ts()),
            )
        except sqlite3.Error as e:
            _log.debug("ai_queue enqueue failed: %s", e)
    return enqueue


def run_collector_loop(controller: Controller, state: RuntimeState) -> None:
    """The sampling loop. Owns its own SQLite connection (thread affinity)."""
    cfg = controller.cfg
    interval = cfg.get("collector", "sample_interval_s", 2)
    backoff = cfg.get("collector", "idle_backoff_s", 10)
    idle_after = cfg.get("collector", "idle_after_s", 90)
    flush_iv = cfg.get("collector", "flush_interval_s", 5)
    flicker = cfg.get("collector", "flicker_min_s", 5)
    recon_window = cfg.get("server", "reconcile_window_s", 3)

    conn = dbmod.connect()
    engine = RulesEngine(conn)
    builder = SpanBuilder(conn, engine, flicker_min_s=flicker,
                          flush_interval_s=flush_iv,
                          enqueue_unknown=_make_enqueue_unknown(conn))
    sampler = ForegroundSampler()
    stopwatch = StopwatchReader(conn)  # §8.7 P1: Clock UIA + web-timer titles
    errlog = RateLimitedLog(_log, interval_s=60)
    stop = controller.stop_event
    paused_before = False
    rules_seen = state.rules_version

    try:
        while not stop.is_set():
            slept = interval
            try:
                if controller.pause_event.is_set():
                    if not paused_before:
                        builder.shutdown(now_ts())
                        paused_before = True
                    stop.wait(1.0)
                    continue
                paused_before = False

                ts = now_ts()
                if idlemod.is_locked():
                    builder.on_locked(ts)
                    slept = backoff
                else:
                    idle_s = idlemod.idle_seconds()
                    if idle_s >= idle_after:
                        builder.on_idle(ts, int(ts - idle_s))
                        slept = backoff
                    else:
                        s = sampler.capture(ts)
                        if s and (s.exe or s.title):
                            url = domain = None
                            title = s.title
                            ext_detail = None
                            if s.exe and s.exe.lower() in parsers.BROWSER_EXES:
                                ev = state.latest_ext_within(ts, recon_window)
                                if ev is not None:  # §8.8 upgrade: URL wins over title
                                    url, domain = ev.url, ev.domain
                                    title = ev.title or title
                                    ext_detail = ev.detail or None
                            builder.on_active(ts, s.exe, s.app_name, title,
                                              url=url, domain=domain, ext_detail=ext_detail)
                        _ = stopwatch.read(s.exe if s else None,
                                           title=s.title if s else None,
                                           domain=domain, ts=ts)
                        slept = interval
                # Phase 7: the API bumps rules_version when a learned rule lands;
                # pick it up here so the very next span close classifies with it.
                if state.rules_version != rules_seen:
                    rules_seen = state.rules_version
                    engine.reload()
                builder.tick(ts)
                state.mark_tick(ts)
            except Exception as e:  # noqa: BLE001 - a bad tick must not kill the loop
                errlog.warn("tick", "collector tick error: %s", e)
            stop.wait(slept)
    finally:
        builder.shutdown(now_ts())
        conn.close()


def _supervise(controller: Controller, state: RuntimeState) -> None:
    """Restart the collector loop on crash: backoff, max 5 restarts/hour."""
    restarts: list[float] = []
    while not controller.stop_event.is_set():
        try:
            run_collector_loop(controller, state)
            return  # clean exit (stop requested)
        except Exception as e:  # noqa: BLE001
            _log.exception("collector loop crashed: %s", e)
            now = time.monotonic()
            restarts = [t for t in restarts if now - t < 3600]
            restarts.append(now)
            if len(restarts) > 5:
                _log.error("collector crashed >5x/hour; giving up until restart")
                if controller.icon is not None:
                    controller.icon.title = "Sanjaya — collector error"
                return
            controller.stop_event.wait(min(30, 2 ** len(restarts)))


# --- server ------------------------------------------------------------------
def _make_server(cfg: configmod.Config, state: RuntimeState, controller: "Controller"):
    """Build a Uvicorn server bound to localhost, runnable on a worker thread."""
    import uvicorn

    from .server.app import create_app

    app = create_app(cfg, state, controller)
    host = cfg.get("server", "host", "127.0.0.1")
    port = int(cfg.get("server", "port", 8756))
    uv_cfg = uvicorn.Config(app, host=host, port=port,
                            log_level="warning", access_log=False)
    return uvicorn.Server(uv_cfg)


# --- entry -------------------------------------------------------------------
def run() -> int:
    inst = SingleInstance()
    cfg = configmod.load(create=True)
    if inst.already_running:
        # Second launch: just open the dashboard and exit (PRD §11).
        Controller(cfg).open_dashboard()
        return 0

    dbmod.init_db()
    controller = Controller(cfg)
    state = RuntimeState()
    state.started_ts = now_ts()

    worker = threading.Thread(target=_supervise, args=(controller, state),
                              name="collector", daemon=True)
    worker.start()

    server = _make_server(cfg, state, controller)
    server_thread = threading.Thread(target=server.run, name="server", daemon=True)
    server_thread.start()

    from .server.scheduler import Scheduler
    scheduler = Scheduler(cfg)
    controller.scheduler = scheduler
    scheduler.start()

    icon = tray.build(controller)
    controller.icon = icon
    _log.info("Sanjaya started (dashboard http://%s:%s)",
              cfg.get("server", "host", "127.0.0.1"), cfg.get("server", "port", 8756))
    try:
        icon.run()  # blocks on the main thread until quit
    finally:
        controller.stop_event.set()
        server.should_exit = True
        scheduler.shutdown()
        worker.join(timeout=10)
        server_thread.join(timeout=10)
        inst.release()
        _log.info("Sanjaya stopped")
    return 0
