"""Foreground sampler (PRD §8.1). One tick captures the foreground window's
exe, friendly app name, and title. pid->exe lookups are cached (invalidated on
pid reuse). Every failure mode (window vanished mid-tick, access denied) is
swallowed so the collector loop never crashes.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

import psutil

from ..log import get

_log = get("collector.sampler")

# A handful of friendly names; anything else falls back to the exe basename.
_FRIENDLY = {
    "chrome.exe": "Google Chrome", "msedge.exe": "Microsoft Edge",
    "brave.exe": "Brave", "firefox.exe": "Mozilla Firefox",
    "code.exe": "Visual Studio Code", "cursor.exe": "Cursor",
    "windsurf.exe": "Windsurf", "winword.exe": "Word", "excel.exe": "Excel",
    "powerpnt.exe": "PowerPoint", "explorer.exe": "File Explorer",
    "acrord32.exe": "Acrobat Reader", "acrobat.exe": "Acrobat",
    "sumatrapdf.exe": "SumatraPDF", "vlc.exe": "VLC", "spotify.exe": "Spotify",
    "windowsterminal.exe": "Windows Terminal", "notepad.exe": "Notepad",
    "claude.exe": "Claude", "chatgpt.exe": "ChatGPT",
}


@dataclass
class Sample:
    ts: int
    exe: str | None
    app_name: str | None
    title: str | None


class ForegroundSampler:
    def __init__(self):
        # lazy Windows imports so the module is importable off-Windows
        if sys.platform != "win32":  # pragma: no cover - non-Windows guard
            raise RuntimeError("ForegroundSampler requires Windows")
        import win32gui
        import win32process
        self._gui = win32gui
        self._proc = win32process
        self._pid_exe: dict[int, tuple[int, str]] = {}  # pid -> (create_time, exe)

    def _exe_for_pid(self, pid: int) -> str | None:
        try:
            p = psutil.Process(pid)
            ct = int(p.create_time())
            cached = self._pid_exe.get(pid)
            if cached and cached[0] == ct:
                return cached[1]
            name = p.name()
            self._pid_exe[pid] = (ct, name)
            return name
        except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
            self._pid_exe.pop(pid, None)
            return None

    def capture(self, ts: int) -> Sample | None:
        """Return the current foreground Sample, or None if nothing is focused."""
        try:
            hwnd = self._gui.GetForegroundWindow()
            if not hwnd:
                return None
            _tid, pid = self._proc.GetWindowThreadProcessId(hwnd)
            exe = self._exe_for_pid(pid) if pid else None
            title = self._gui.GetWindowText(hwnd) or None
            app_name = _FRIENDLY.get((exe or "").lower(), exe)
            return Sample(ts=ts, exe=exe, app_name=app_name, title=title)
        except Exception as e:  # noqa: BLE001 - a bad tick must never kill the loop
            _log.debug("capture failed: %s", e)
            return None
