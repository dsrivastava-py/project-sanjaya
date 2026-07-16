"""Idle and lock detection (PRD §8.2).

  * ``idle_seconds`` — seconds since the last keyboard/mouse input via
    ``GetLastInputInfo``.
  * ``is_locked`` — whether the workstation is locked, detected by asking which
    desktop currently receives input: when locked it is the secure ``Winlogon``
    desktop (or ``OpenInputDesktop`` fails outright), never ``Default``.

Both are cheap ctypes calls; no message-loop window is required, which keeps the
locked path free of wakeups.
"""
from __future__ import annotations

import ctypes
import sys

_IS_WIN = sys.platform == "win32"

if _IS_WIN:
    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32

    class _LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    _DESKTOP_SWITCHDESKTOP = 0x0100
    _UOI_NAME = 2


def idle_seconds() -> float:
    """Seconds since the last user input (0.0 if unavailable)."""
    if not _IS_WIN:  # pragma: no cover
        return 0.0
    lii = _LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(lii)
    if not _user32.GetLastInputInfo(ctypes.byref(lii)):
        return 0.0
    millis = _kernel32.GetTickCount() - lii.dwTime
    return max(0.0, millis / 1000.0)


def is_locked() -> bool:
    """True if the workstation is locked (best-effort)."""
    if not _IS_WIN:  # pragma: no cover
        return False
    h = _user32.OpenInputDesktop(0, False, _DESKTOP_SWITCHDESKTOP)
    if not h:
        return True  # cannot open the input desktop -> secure desktop is up
    try:
        needed = ctypes.c_ulong(0)
        _user32.GetUserObjectInformationW(h, _UOI_NAME, None, 0, ctypes.byref(needed))
        buf = ctypes.create_unicode_buffer(needed.value // 2 + 1)
        _user32.GetUserObjectInformationW(h, _UOI_NAME, buf, needed.value, ctypes.byref(needed))
        return buf.value.lower() != "default"
    finally:
        _user32.CloseDesktop(h)
