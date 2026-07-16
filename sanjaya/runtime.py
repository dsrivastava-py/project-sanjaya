"""Shared, thread-safe runtime state bridging the collector thread and the
FastAPI server thread (PRD §5, §8.8). Two concerns:

  * collector heartbeat — the sampler marks each tick so ``/status`` can report
    how fresh the data is and whether the loop is alive.
  * extension bridge — the ``/ingest/browser`` endpoint records the latest
    browser/YouTube event; the collector consults it to *upgrade* a foreground
    browser span with url/domain/detail when the two agree within ±3s (§8.8).

The state lives in memory only. Extension events that arrive while the browser
is not foreground are simply overwritten by the next event — they never become
foreground spans on their own (§8.8).
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass
class ExtEvent:
    """One browser-tab observation from the extension (§8.8 payload)."""
    ts: int
    url: str | None = None
    title: str | None = None
    domain: str | None = None
    audible: bool = False
    event: str | None = None
    detail: dict = field(default_factory=dict)   # youtube {video_id,video_title,channel,playing,position}


class RuntimeState:
    """Thread-safe box shared between the collector and the server."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_tick_ts: int = 0
        self._last_ext: ExtEvent | None = None
        self._last_ext_ts: int = 0
        self._rules_version: int = 0
        self.started_ts: int = 0

    # -- rules reload signal (Phase 7) ---------------------------------------
    # The collector thread owns its RulesEngine instance; when the API creates a
    # learned rule it bumps this counter and the collector calls engine.reload()
    # on its next tick. Monotonic int — no rule data crosses threads.
    def bump_rules(self) -> None:
        with self._lock:
            self._rules_version += 1

    @property
    def rules_version(self) -> int:
        with self._lock:
            return self._rules_version

    # -- collector heartbeat -------------------------------------------------
    def mark_tick(self, ts: int) -> None:
        with self._lock:
            if ts > self._last_tick_ts:
                self._last_tick_ts = ts

    @property
    def last_tick_ts(self) -> int:
        with self._lock:
            return self._last_tick_ts

    # -- extension bridge ----------------------------------------------------
    def record_ext_event(self, ev: ExtEvent) -> None:
        with self._lock:
            if ev.ts >= self._last_ext_ts:
                self._last_ext = ev
                self._last_ext_ts = ev.ts

    @property
    def last_ext_ts(self) -> int:
        with self._lock:
            return self._last_ext_ts

    def latest_ext_within(self, ts: int, window_s: int) -> ExtEvent | None:
        """Return the last extension event iff it lands within ±window of ``ts``
        (the ±3s reconciliation window, §8.8). Otherwise None."""
        with self._lock:
            ev = self._last_ext
            if ev is None:
                return None
            return ev if abs(ts - ev.ts) <= window_s else None
