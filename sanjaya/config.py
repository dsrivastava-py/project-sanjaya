"""User configuration. ``config.toml`` is created on first run from the defaults
below (PRD §6.1) and then owned by the user. Unknown/missing keys fall back to
the defaults via a deep-merge so an old config never breaks a new build.
"""
from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from . import paths

# The canonical default config. Written verbatim to config.toml on first run so
# the user has a fully-commented file to edit.
DEFAULT_CONFIG_TOML = """\
# Sanjaya configuration. Created on first run; edit freely. Missing keys fall
# back to built-in defaults, so you only need to keep what you change.
schema_version = 1

[general]
timezone = "Asia/Kolkata"   # all rendering converts UTC -> this zone
day_start_hour = 4          # a 1am session counts to the previous day

[collector]
sample_interval_s = 2       # foreground poll cadence while active
idle_backoff_s = 10         # slower poll once idle
idle_after_s = 90           # seconds of no input before an idle span opens
flush_interval_s = 5        # open span upserted this often (bounds crash loss)
flicker_min_s = 5           # spans shorter than this are merged/dropped

[server]
host = "127.0.0.1"          # localhost bind ONLY
port = 8756
reconcile_window_s = 3      # extension event within ±this of a sample upgrades the span (§8.8)
app_window = true           # open the dashboard as a chromeless desktop window (Edge/Chrome --app); false = normal browser tab

[ai]
classify_model = "llama-3.1-8b-instant"
narrative_model = "llama-3.3-70b-versatile"
summary_time = "21:30"
ai_daily_token_cap = 300000
debug_ai_payloads = false
# One line about the user, injected into every prompt (§9.3). Edit to taste.
user_context = "Runs web agency DevsCrest; college student; dual degree; preparing for placements."

[focus]
# focus_score = 100 * (w_productive*P + w_deep*D + w_switch*S)  (PRD §8.6)
w_productive = 0.5
w_deep = 0.3
w_switch = 0.2
deep_block_min_minutes = 25       # a "deep block" must run at least this long
deep_block_target_minutes = 90    # D saturates at this longest-block length
deep_interruption_max_s = 120     # gaps under this don't break a deep block
switch_flicker_s = 10             # spans under this don't count as a switch
switch_norm_per_hour = 30         # S floors at this switches/hour

[privacy]
retention_months = 0        # 0 = keep raw spans forever
"""


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _defaults() -> dict:
    return tomllib.loads(DEFAULT_CONFIG_TOML)


class Config:
    """Read-only view over the merged config dict with small typed helpers."""

    def __init__(self, data: dict):
        self._d = data

    def __getitem__(self, section: str) -> dict:
        return self._d[section]

    def section(self, name: str) -> dict:
        return self._d.get(name, {})

    def get(self, section: str, key: str, default: Any = None) -> Any:
        return self._d.get(section, {}).get(key, default)

    @property
    def timezone(self) -> str:
        return self.get("general", "timezone", "Asia/Kolkata")

    @property
    def day_start_hour(self) -> int:
        return int(self.get("general", "day_start_hour", 4))

    @property
    def as_dict(self) -> dict:
        return self._d


def load(path: Path | None = None, create: bool = True) -> Config:
    """Load config, writing the default file on first run."""
    path = path or paths.CONFIG_PATH
    defaults = _defaults()
    if not path.exists():
        if create:
            paths.ensure_dirs()
            path.write_text(DEFAULT_CONFIG_TOML, encoding="utf-8")
        return Config(defaults)
    user = tomllib.loads(path.read_text(encoding="utf-8"))
    return Config(_deep_merge(defaults, user))
