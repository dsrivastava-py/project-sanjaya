"""Daily AI token budget (PRD §9.4). A per-local-day counter in ``settings`` plus
a soft cap (``ai_daily_token_cap``, default 300k) that pauses non-essential jobs
with a dashboard-visible notice. Nothing here blocks hard — it lets the caller
decide to skip a batch and surfaces ``ai_budget_paused`` for the UI.
"""
from __future__ import annotations

from ..db import get_setting, set_setting
from ..timeutil import local_day, now_ts


def _key(date: str) -> str:
    return f"ai_tokens_{date}"


def _today(cfg) -> str:
    return local_day(now_ts(), cfg.timezone, cfg.day_start_hour)


def cap(cfg, conn=None) -> int:
    if conn is not None:
        raw = get_setting(conn, "ai_daily_token_cap", None)
        if raw is not None:
            try:
                return int(raw)
            except (TypeError, ValueError):
                pass
    return int(cfg.get("ai", "ai_daily_token_cap", 300000))


def tokens_today(conn, cfg) -> int:
    return int(get_setting(conn, _key(_today(cfg)), 0) or 0)


def add_tokens(conn, cfg, n: int) -> int:
    date = _today(cfg)
    total = int(get_setting(conn, _key(date), 0) or 0) + int(n or 0)
    set_setting(conn, _key(date), total)
    return total


def over_cap(conn, cfg) -> bool:
    paused = tokens_today(conn, cfg) >= cap(cfg, conn)
    set_setting(conn, "ai_budget_paused", 1 if paused else 0)
    return paused
