"""Media session watcher (PRD §8.5 / §6, P1 — full impl in Phase 9).

Reads now-playing metadata (title, artist, playback status) from the Windows
``GlobalSystemMediaTransportControls`` API via ``winsdk``. ``winsdk`` is an
optional dependency (see pyproject ``[project.optional-dependencies].media``);
when it is absent this degrades to a no-op and never affects the collector.
"""
from __future__ import annotations

from ..log import get

_log = get("collector.media")


class MediaWatcher:
    def __init__(self):
        self.available = False
        try:
            import winsdk.windows.media.control  # noqa: F401
            self.available = True
        except Exception:  # noqa: BLE001 - optional dependency / API drift
            _log.info("winsdk not available; media metadata disabled (P1).")

    def current(self) -> dict | None:
        """Return {app, title, artist, status} for the active media session,
        or None. Stub until Phase 9; safe to call."""
        if not self.available:
            return None
        return None  # TODO(Phase 9): query the session manager and map fields
