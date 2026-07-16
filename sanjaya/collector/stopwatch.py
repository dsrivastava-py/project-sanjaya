"""Stopwatch reader (PRD §8.7, P1 — Phase 9 implementation).

Best-effort: only when Windows Clock is foreground do we attach a lazy UIA
reader to scrape the stopwatch/timer value. UIA element names drift across app
updates, so all selectors live in one constants block and any failure degrades
silently to nothing (never crashes, logs once per session).

Web timers (known domains) are read from the tab title by regex — the last seen
value before the tab goes away is recorded as ``source='web:<domain>'``.

On transition playing→paused (value stops advancing) or the timer leaving the
foreground while a value exists, a row lands in ``stopwatch_readings``.
"""
from __future__ import annotations

import re
import sqlite3

from ..log import get
from ..timeutil import now_ts

_log = get("collector.stopwatch")

# --- Windows Clock identifiers (isolated: an app update is a one-line fix) ----
CLOCK_EXES = {"time.exe", "clock.exe"}
CLOCK_AUMID = "Microsoft.WindowsAlarms"
CLOCK_WINDOW_TITLES = ("Clock", "Alarms & Clock")
# candidate AutomationIds for the big time display, newest first
CLOCK_VALUE_AUTOMATION_IDS = ("StopwatchTimeText", "TimerValue", "LapTimeText")

# --- web timers (§8.7): title pattern + known domains --------------------------
WEB_TIMER_DOMAINS = {"pomofocus.io", "google.com"}
_TIME_RX = re.compile(r"(?<![\d.])(\d{1,2}):(\d{2})(?::(\d{2}))?(?![\d.])")

_PAUSE_AFTER_S = 4   # value frozen this long while foreground => 'paused'


def parse_time_to_seconds(text: str) -> int | None:
    """First H:MM:SS or M:SS reading in ``text`` → seconds."""
    m = _TIME_RX.search(text or "")
    if not m:
        return None
    a, b, c = m.group(1), m.group(2), m.group(3)
    if c is not None:
        return int(a) * 3600 + int(b) * 60 + int(c)
    return int(a) * 60 + int(b)


def record_reading(conn: sqlite3.Connection, *, source: str, label: str | None,
                   value_s: int, event: str = "paused", ts: int | None = None) -> None:
    try:
        conn.execute(
            "INSERT INTO stopwatch_readings(ts, source, label, last_value_s, event) "
            "VALUES(?,?,?,?,?)",
            (ts or now_ts(), source, label, int(value_s), event),
        )
    except sqlite3.Error as e:
        _log.debug("stopwatch reading insert failed: %s", e)


class StopwatchReader:
    """Feed with each tick's foreground exe/title (+ optional domain). Emits
    readings into ``conn`` on pause/close transitions."""

    def __init__(self, conn: sqlite3.Connection | None = None):
        self._conn = conn
        self.available = False
        try:
            import uiautomation  # noqa: F401
            self.available = True
        except Exception:  # noqa: BLE001
            _log.info("uiautomation not available; Clock stopwatch reader disabled (P1).")
        self._logged_fail = False
        self._last: dict | None = None   # {source, label, value_s, ts} for transition detection

    # -- Windows Clock via UIA -------------------------------------------------
    def _read_clock_uia(self) -> tuple[str | None, int | None]:
        try:
            import uiautomation as uia
            win = None
            for t in CLOCK_WINDOW_TITLES:
                w = uia.WindowControl(searchDepth=1, Name=t)
                if w.Exists(0, 0):
                    win = w
                    break
            if win is None:
                return None, None
            for aid in CLOCK_VALUE_AUTOMATION_IDS:
                el = win.Control(searchDepth=12, AutomationId=aid)
                if el.Exists(0, 0):
                    val = parse_time_to_seconds(el.Name or "")
                    if val is not None:
                        return aid, val
            for el in win.GetChildren():
                val = parse_time_to_seconds(getattr(el, "Name", "") or "")
                if val is not None:
                    return None, val
        except Exception as e:  # noqa: BLE001 — UIA breakage must never crash the loop
            if not self._logged_fail:
                self._logged_fail = True
                _log.info("Clock UIA read failed (disabled for this session): %s", e)
        return None, None

    # -- public tick API ---------------------------------------------------------
    def read(self, exe: str | None, title: str | None = None,
             domain: str | None = None, ts: int | None = None) -> dict | None:
        """Sample current stopwatch state; on transition away/pause, record the
        last value. Safe to call every tick."""
        ts = ts or now_ts()
        current: dict | None = None

        if self.available and (exe or "").lower() in CLOCK_EXES:
            label, val = self._read_clock_uia()
            if val is not None:
                current = {"source": "windows_clock", "label": label, "value_s": val, "ts": ts}
        elif domain and any(domain == d or domain.endswith("." + d) for d in WEB_TIMER_DOMAINS):
            val = parse_time_to_seconds(title or "")
            if val is not None:
                current = {"source": f"web:{domain}", "label": None, "value_s": val, "ts": ts}

        prev = self._last
        if prev is not None and (current is None or current["source"] != prev["source"]):
            # timer left the foreground (closed / switched away) — flush last value
            if self._conn is not None:
                record_reading(self._conn, source=prev["source"], label=prev["label"],
                               value_s=prev["value_s"], event="closed", ts=ts)
        elif prev is not None and current is not None \
                and current["value_s"] == prev["value_s"] and ts - prev["ts"] >= _PAUSE_AFTER_S:
            # value stopped advancing while still foreground -> paused (record once)
            if self._conn is not None and not prev.get("_paused_recorded"):
                record_reading(self._conn, source=prev["source"], label=prev["label"],
                               value_s=prev["value_s"], event="paused", ts=ts)
                prev["_paused_recorded"] = True
            current = prev  # keep frozen ts + the pause-recorded marker
        self._last = current
        return current
