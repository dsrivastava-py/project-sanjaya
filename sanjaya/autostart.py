"""Start-with-Windows toggle (PRD §11): a shortcut in ``shell:startup`` that
launches Sanjaya windowless via ``pythonw -m sanjaya``. Best-effort — any
failure is reported to the caller, never raised into the tray loop.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from . import paths

_SHORTCUT_NAME = "Sanjaya.lnk"


def _startup_dir() -> Path:
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    return paths.DATA_DIR / "startup"


def _shortcut_path() -> Path:
    return _startup_dir() / _SHORTCUT_NAME


def enabled() -> bool:
    return _shortcut_path().exists()


def _pythonw() -> str:
    exe = Path(sys.executable)
    cand = exe.with_name("pythonw.exe")
    return str(cand if cand.exists() else exe)


def enable() -> bool:
    try:
        import win32com.client
        shell = win32com.client.Dispatch("WScript.Shell")
        sc = shell.CreateShortcut(str(_shortcut_path()))
        sc.TargetPath = _pythonw()
        sc.Arguments = "-m sanjaya"
        sc.WorkingDirectory = str(paths.ROOT)
        sc.Description = "Sanjaya activity journal"
        sc.Save()
        return True
    except Exception:  # noqa: BLE001
        return False


def disable() -> bool:
    try:
        p = _shortcut_path()
        if p.exists():
            p.unlink()
        return True
    except OSError:
        return False
