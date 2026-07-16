"""Single-instance guard via a named mutex (PRD §11). A second launch fails to
acquire ``Global\\SanjayaSingleton`` and can just open the dashboard instead.
"""
from __future__ import annotations

import sys

MUTEX_NAME = "Local\\SanjayaSingleton"


class SingleInstance:
    def __init__(self, name: str = MUTEX_NAME):
        self._name = name
        self._handle = None
        self.already_running = False
        if sys.platform == "win32":
            import win32api
            import win32event
            import winerror
            self._handle = win32event.CreateMutex(None, False, name)
            self.already_running = (
                win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS
            )

    def release(self) -> None:
        if self._handle is not None:
            import win32api
            win32api.CloseHandle(self._handle)
            self._handle = None
