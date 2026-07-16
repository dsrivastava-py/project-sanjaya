"""Goals engine (PRD §10.4, Phase 8): goal evaluation, streaks, rollups.

Progress is always *recomputed from spans* (the source of truth); closed periods
are cached in ``goal_progress`` (write-through) so streak walks stay cheap. Span
edits invalidate the affected periods (:func:`invalidate_progress`) and a nightly
rollup backfills/refreshes the cache.

Period semantics
  * daily    — one local day honoring ``day_start_hour`` (§13.8)
  * weekly   — Monday..Sunday (ISO), i.e. Monday 04:00 → next Monday 04:00
  * monthly  — 1st of month; yearly — Jan 1st
  * ``active_days`` (JSON list, Mon=0..Sun=6) applies to daily goals only;
    inactive days are *skipped*: they neither break nor extend a streak.

Streak semantics (unit-tested; Phase 8 acceptance)
  * walk periods from goal creation to the current period
  * met → streak +1 · missed → streak resets · skipped → unchanged
  * the pending current period: at_least not-yet-met → *pending* (still winnable,
    treated like a skip); at_most over cap → *missed* (irreversible); met-so-far
    → counts as met
  * ``best`` is the longest met-run since the goal's creation period.

No imports from reporting.py (reporting imports this module).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

from .timeutil import day_bounds, local_day, now_ts

PERIODS = ("daily", "weekly", "monthly", "yearly")
DIRECTIONS = ("at_least", "at_most")

# History strip lengths for goal cards (§10.4) — also the cap on how far back a
# streak walk goes (older periods are simply not revisited each request).
HISTORY_LEN = {"daily": 42, "weekly": 12, "monthly": 12, "yearly": 3}
_MAX_PERIODS = {"daily": 400, "weekly": 120, "monthly": 60, "yearly": 20}

_INACTIVE_KINDS = ("idle", "locked")


# --- period math (all on 'YYYY-MM-DD' strings) --------------------------------
def _d(date: str) -> datetime:
    return datetime.strptime(date, "%Y-%m-%d")


def period_start_of(date: str, period: str) -> str:
    """Canonical period key containing a local day."""
    d = _d(date)
    if period == "daily":
        return date
    if period == "weekly":
        return (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")
    if period == "monthly":
        return d.replace(day=1).strftime("%Y-%m-%d")
    if period == "yearly":
        return d.replace(month=1, day=1).strftime("%Y-%m-%d")
    raise ValueError(f"unknown period {period!r}")


def next_period_start(period_start: str, period: str) -> str:
    d = _d(period_start)
    if period == "daily":
        return (d + timedelta(days=1)).strftime("%Y-%m-%d")
    if period == "weekly":
        return (d + timedelta(days=7)).strftime("%Y-%m-%d")
    if period == "monthly":
        return (d.replace(day=28) + timedelta(days=4)).replace(day=1).strftime("%Y-%m-%d")
    if period == "yearly":
        return d.replace(year=d.year + 1).strftime("%Y-%m-%d")
    raise ValueError(f"unknown period {period!r}")


def prev_period_start(period_start: str, period: str) -> str:
    d = _d(period_start)
    if period == "daily":
        return (d - timedelta(days=1)).strftime("%Y-%m-%d")
    if period == "weekly":
        return (d - timedelta(days=7)).strftime("%Y-%m-%d")
    if period == "monthly":
        return (d - timedelta(days=1)).replace(day=1).strftime("%Y-%m-%d")
    if period == "yearly":
        return d.replace(year=d.year - 1).strftime("%Y-%m-%d")
    raise ValueError(f"unknown period {period!r}")


def period_bounds(period_start: str, period: str, tz: str, day_start_hour: int) -> tuple[int, int]:
    """[lo, hi) UTC epoch bounds of a period, honoring day_start_hour (§13.8)."""
    lo = day_bounds(period_start, tz, day_start_hour)[0]
    hi = day_bounds(next_period_start(period_start, period), tz, day_start_hour)[0]
    return lo, hi


def current_period_start(cfg, period: str) -> str:
    today = local_day(now_ts(), cfg.timezone, cfg.day_start_hour)
    return period_start_of(today, period)


# --- goal helpers --------------------------------------------------------------
def active_days_of(goal: dict) -> list[int] | None:
    """Parsed active_days ([0..6], Mon=0) or None = every day."""
    raw = goal.get("active_days")
    if not raw:
        return None
    try:
        vals = json.loads(raw) if isinstance(raw, str) else list(raw)
        days = sorted({int(v) for v in vals if 0 <= int(v) <= 6})
        return days or None
    except (ValueError, TypeError):
        return None


def is_active_period(goal: dict, period_start: str) -> bool:
    """False only for daily goals on a weekday outside active_days."""
    if goal["period"] != "daily":
        return True
    days = active_days_of(goal)
    if days is None:
        return True
    return _d(period_start).weekday() in days


def _met(direction: str, minutes: int, target: int) -> bool:
    return minutes >= target if direction == "at_least" else minutes <= target


def goal_minutes(conn: sqlite3.Connection, goal: dict, lo: int, hi: int) -> int:
    """Minutes of matching span time inside [lo, hi), clipped at the bounds
    (§13.8 day-boundary honesty). Manual spans count like any categorized span;
    idle/locked never count."""
    where = "start_ts < ? AND end_ts > ? AND kind NOT IN ('idle','locked')"
    params: list = [hi, lo]
    if goal.get("project_id") is not None:
        where += " AND project_id = ?"
        params.append(goal["project_id"])
    elif goal.get("category_id") is not None:
        where += " AND category_id = ?"
        params.append(goal["category_id"])
    row = conn.execute(
        f"SELECT COALESCE(SUM(MIN(end_ts, ?) - MAX(start_ts, ?)), 0) AS secs "
        f"FROM spans WHERE {where}",
        [hi, lo, *params],
    ).fetchone()
    return int(row["secs"]) // 60


# --- evaluation + cache ---------------------------------------------------------
def evaluate(conn: sqlite3.Connection, cfg, goal: dict, period_start: str,
             *, use_cache: bool = True) -> dict:
    """Progress of one goal for one period. Closed periods are cached in
    goal_progress (write-through); the current (pending) period never is."""
    period = goal["period"]
    closed = period_start < current_period_start(cfg, period)
    if use_cache and closed:
        row = conn.execute(
            "SELECT minutes, met FROM goal_progress WHERE goal_id=? AND period_start=?",
            (goal["id"], period_start),
        ).fetchone()
        if row:
            return {"period_start": period_start, "minutes": row["minutes"],
                    "met": bool(row["met"]), "closed": True}
    lo, hi = period_bounds(period_start, period, cfg.timezone, cfg.day_start_hour)
    minutes = goal_minutes(conn, goal, lo, hi)
    met = _met(goal["direction"], minutes, goal["target_minutes"])
    if closed:
        conn.execute(
            "INSERT INTO goal_progress(goal_id, period_start, minutes, met, computed_ts) "
            "VALUES(?,?,?,?,?) ON CONFLICT(goal_id, period_start) DO UPDATE SET "
            "minutes=excluded.minutes, met=excluded.met, computed_ts=excluded.computed_ts",
            (goal["id"], period_start, minutes, int(met), now_ts()),
        )
    return {"period_start": period_start, "minutes": minutes, "met": met, "closed": closed}


def _first_period(cfg, goal: dict, cur: str) -> str:
    """Creation period, clamped to _MAX_PERIODS back from ``cur``."""
    period = goal["period"]
    created_day = local_day(goal["created_ts"], cfg.timezone, cfg.day_start_hour)
    first = period_start_of(created_day, period)
    floor = cur
    for _ in range(_MAX_PERIODS[period] - 1):
        floor = prev_period_start(floor, period)
    return max(first, floor)


def _statuses(conn: sqlite3.Connection, cfg, goal: dict, today: str) -> list[dict]:
    """Per-period status from the goal's (clamped) creation period to ``today``:
    [{period_start, minutes, status}] with status met|missed|skipped|pending."""
    period = goal["period"]
    cur = period_start_of(today, period)
    first = _first_period(cfg, goal, cur)
    cache = {
        r["period_start"]: r
        for r in conn.execute(
            "SELECT period_start, minutes, met FROM goal_progress WHERE goal_id=?",
            (goal["id"],),
        )
    }
    out: list[dict] = []
    p = first
    while p <= cur:
        if not is_active_period(goal, p):
            out.append({"period_start": p, "minutes": 0, "status": "skipped"})
        elif p < cur and p in cache:
            r = cache[p]
            out.append({"period_start": p, "minutes": r["minutes"],
                        "status": "met" if r["met"] else "missed"})
        else:
            ev = evaluate(conn, cfg, goal, p, use_cache=False)
            if p < cur:
                status = "met" if ev["met"] else "missed"
            elif goal["direction"] == "at_least":
                # pending current period: not-yet-met is still winnable
                status = "met" if ev["met"] else "pending"
            else:
                # at_most: blowing the cap mid-period is irreversible
                status = "met" if ev["met"] else "missed"
            out.append({"period_start": p, "minutes": ev["minutes"], "status": status})
        p = next_period_start(p, period)
    return out


def _streaks_from(statuses: list[dict]) -> dict:
    run = best = 0
    for s in statuses:
        if s["status"] == "met":
            run += 1
            best = max(best, run)
        elif s["status"] == "missed":
            run = 0
        # skipped/pending: neither break nor extend
    current = 0
    for s in reversed(statuses):
        if s["status"] == "met":
            current += 1
        elif s["status"] == "missed":
            break
    return {"current": current, "best": best}


def streaks(conn: sqlite3.Connection, cfg, goal: dict, today: str | None = None) -> dict:
    today = today or local_day(now_ts(), cfg.timezone, cfg.day_start_hour)
    return _streaks_from(_statuses(conn, cfg, goal, today))


# --- API-facing shapes -----------------------------------------------------------
def goal_card(conn: sqlite3.Connection, cfg, goal: dict, today: str | None = None) -> dict:
    """Full card for the Goals page (§10.4): current progress, streaks, history."""
    today = today or local_day(now_ts(), cfg.timezone, cfg.day_start_hour)
    period = goal["period"]
    sts = _statuses(conn, cfg, goal, today)
    cur = sts[-1] if sts else {"period_start": period_start_of(today, period),
                               "minutes": 0, "status": "pending"}
    return {
        "id": goal["id"],
        "name": goal["name"],
        "period": period,
        "direction": goal["direction"],
        "target_minutes": goal["target_minutes"],
        "category_id": goal.get("category_id"),
        "project_id": goal.get("project_id"),
        "active_days": active_days_of(goal),
        "created_ts": goal["created_ts"],
        "archived": bool(goal.get("archived")),
        "period_start": cur["period_start"],
        "minutes": cur["minutes"],
        "status": cur["status"],
        "met": cur["status"] == "met",
        "streak": _streaks_from(sts),
        "history": sts[-HISTORY_LEN[period]:],
    }


def goals_for_day(conn: sqlite3.Connection, cfg, date: str) -> list[dict]:
    """Daily-goal meters for the Today page (§10.1): progress for ``date`` plus
    the streak flame count *as of* that date (historical day views stay honest)."""
    rows = conn.execute(
        "SELECT * FROM goals WHERE archived=0 AND period='daily' ORDER BY id"
    ).fetchall()
    lo, hi = period_bounds(date, "daily", cfg.timezone, cfg.day_start_hour)
    out = []
    for r in rows:
        goal = dict(r)
        minutes = goal_minutes(conn, goal, lo, hi)
        st = streaks(conn, cfg, goal, today=date)
        out.append({
            "id": goal["id"], "name": goal["name"], "direction": goal["direction"],
            "target_minutes": goal["target_minutes"], "minutes": minutes,
            "category_id": goal["category_id"], "project_id": goal["project_id"],
            "met": _met(goal["direction"], minutes, goal["target_minutes"]),
            "active_today": is_active_period(goal, date),
            "streak": st["current"], "best_streak": st["best"],
        })
    return out


def week_goal_streaks(conn: sqlite3.Connection, cfg, week_start: str) -> str:
    """Compact streak line for the weekly-insight prompt (§9.3 C)."""
    week_end = (_d(week_start) + timedelta(days=6)).strftime("%Y-%m-%d")
    rows = conn.execute("SELECT * FROM goals WHERE archived=0 ORDER BY id").fetchall()
    parts = []
    for r in rows:
        goal = dict(r)
        st = streaks(conn, cfg, goal, today=week_end)
        parts.append(f"{goal['name']}: streak {st['current']} (best {st['best']})")
    return "; ".join(parts) if parts else "none"


# --- cache maintenance ------------------------------------------------------------
def invalidate_progress(conn: sqlite3.Connection, cfg, lo_ts: int, hi_ts: int) -> None:
    """Drop cached goal_progress rows whose period touches [lo_ts, hi_ts) — called
    after span create/edit/delete so progress recomputes lazily from spans."""
    tz, dsh = cfg.timezone, cfg.day_start_hour
    d0 = local_day(lo_ts, tz, dsh)
    d1 = local_day(max(lo_ts, hi_ts - 1), tz, dsh)
    if (_d(d1) - _d(d0)).days > 366:          # absurd range: just flush the cache
        conn.execute("DELETE FROM goal_progress")
        return
    keys: set[str] = set()
    d = d0
    while d <= d1:
        for period in PERIODS:
            keys.add(period_start_of(d, period))
        d = next_period_start(d, "daily")
    ph = ",".join("?" for _ in keys)
    conn.execute(f"DELETE FROM goal_progress WHERE period_start IN ({ph})", tuple(keys))


def rollup(conn: sqlite3.Connection, cfg) -> int:
    """Nightly job: cache closed-period progress for every active goal. The most
    recently closed period is recomputed unconditionally (its spans changed all
    day); older uncached periods are backfilled. Returns periods computed."""
    count = 0
    for r in conn.execute("SELECT * FROM goals WHERE archived=0").fetchall():
        goal = dict(r)
        period = goal["period"]
        cur = current_period_start(cfg, period)
        force = prev_period_start(cur, period)
        first = _first_period(cfg, goal, cur)
        cached = {
            row["period_start"]
            for row in conn.execute(
                "SELECT period_start FROM goal_progress WHERE goal_id=?", (goal["id"],)
            )
        }
        p = first
        while p < cur:
            if p == force or p not in cached:
                evaluate(conn, cfg, goal, p, use_cache=False)
                count += 1
            p = next_period_start(p, period)
    return count
