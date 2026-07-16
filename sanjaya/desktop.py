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

import os
import shutil
import subprocess
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
