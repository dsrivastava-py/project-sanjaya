"""Open the dashboard as a desktop app window (PRD §11 polish).

"Run like software, not a webapp": launch the local dashboard in a Chromium
``--app`` window — a standalone frame with no tabs, address bar, or bookmarks —
so Sanjaya looks and feels like a native desktop app. This is purely how the UI
is *shown*; the architecture is unchanged (still the same localhost SPA the tray
already opened), so it cannot hinder the collector, server, or data path. If no
Chromium browser is found, we fall back to the default browser.

Zero new dependencies: Edge ships with Windows; Chrome is detected if present.
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
import webbrowser

from .log import get

_log = get("desktop")

# Edge first (always present on Win10/11), then Chrome. Env-var roots cover both
# 64- and 32-bit install locations without hard-coding a drive letter.
_CHROMIUM_CANDIDATES = (
    ("ProgramFiles(x86)", r"Microsoft\Edge\Application\msedge.exe"),
    ("ProgramFiles", r"Microsoft\Edge\Application\msedge.exe"),
    ("ProgramFiles", r"Google\Chrome\Application\chrome.exe"),
    ("ProgramFiles(x86)", r"Google\Chrome\Application\chrome.exe"),
    ("LOCALAPPDATA", r"Google\Chrome\Application\chrome.exe"),
)


def _find_installed_pwa() -> str | None:
    """Path to an installed Sanjaya PWA shortcut, if the user has run
    Edge/Chrome's "Install this site as an app". Such a window carries the app's
    own gold-eye icon and its own taskbar identity — unlike a plain ``--app``
    window, which shows the Edge/Chrome logo. We detect it by scanning the Start
    Menu / Desktop for a ``Sanjaya*.lnk`` whose target is msedge/chrome and whose
    arguments contain ``--app-id`` (the signature of an installed PWA launcher)."""
    if sys.platform != "win32":
        return None
    try:
        import win32com.client  # provided by pywin32 (already a dependency)
        shell = win32com.client.Dispatch("WScript.Shell")
    except Exception as e:  # noqa: BLE001 - COM/pywin32 unavailable → just skip
        _log.debug("PWA lookup skipped (no WScript.Shell): %s", e)
        return None

    roots = [
        os.path.join(os.environ.get("APPDATA", ""),
                     r"Microsoft\Windows\Start Menu\Programs"),
        os.path.join(os.environ.get("USERPROFILE", ""), "Desktop"),
    ]
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        for lnk in glob.glob(os.path.join(root, "**", "*.lnk"), recursive=True):
            if "sanjaya" not in os.path.basename(lnk).lower():
                continue
            try:
                sc = shell.CreateShortcut(lnk)
                args = sc.Arguments or ""
                target = (sc.TargetPath or "").lower()
            except Exception:  # noqa: BLE001 - unreadable shortcut → ignore
                continue
            # Distinguish the PWA launcher from Sanjaya's own pythonw shortcut.
            if "--app-id=" in args and ("msedge" in target or "chrome" in target):
                return lnk
    return None


def _find_chromium() -> str | None:
    for root_env, rel in _CHROMIUM_CANDIDATES:
        root = os.environ.get(root_env)
        if root:
            path = os.path.join(root, rel)
            if os.path.isfile(path):
                return path
    # last resort: whatever is on PATH
    for exe in ("msedge", "chrome", "chromium"):
        found = shutil.which(exe)
        if found:
            return found
    return None


def open_dashboard(url: str, *, app_window: bool = True) -> None:
    """Open ``url``. In app-window mode, use a chromeless Chromium frame; else the
    default browser. Any failure degrades to :func:`webbrowser.open` — the
    dashboard must always be reachable."""
    if app_window:
        # Best: an installed PWA — its window shows the gold-eye icon and stands
        # alone on the taskbar. os.startfile launches the shortcut's own target.
        pwa = _find_installed_pwa()
        if pwa is not None:
            try:
                os.startfile(pwa)  # type: ignore[attr-defined]  # noqa: S606 (win32 only)
                _log.info("opened dashboard via installed app: %s", os.path.basename(pwa))
                return
            except OSError as e:
                _log.warning("installed-app launch failed (%s); falling back", e)

        browser = _find_chromium()
        if browser:
            # A dedicated user-data-dir keeps the app window isolated from the
            # user's normal browsing profile (own window list, no tab bleed).
            profile = os.path.join(
                os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
                "Sanjaya", "app-profile",
            )
            try:
                subprocess.Popen(
                    [browser, f"--app={url}", f"--user-data-dir={profile}",
                     "--window-size=1440,900", "--no-first-run"],
                    close_fds=True,
                )
                _log.info("opened dashboard as app window via %s", os.path.basename(browser))
                return
            except OSError as e:
                _log.warning("app-window launch failed (%s); falling back to browser", e)
        else:
            _log.info("no Chromium browser found; opening dashboard in default browser")
    webbrowser.open(url)
