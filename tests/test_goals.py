"""Unit tests for the goals engine (PRD §10.4, Phase 8 acceptance): period math,
clipped minute sums across day boundaries + manual spans, streak semantics
(incl. at_most direction and skipped inactive days), cache write-through,
invalidation, and the nightly rollup. Pure logic — fixed dates, temp DB.
"""
from __future__ import annotations

import json

from sanjaya import db as dbmod, goals
from sanjaya.timeutil import day_bounds

TZ = "Asia/Kolkata"
DSH = 4


class Cfg:
    timezone = TZ
    day_start_hour = DSH


CFG = Cfg()

# Fixed, all in the past relative to any real clock this suite runs under.
MON = "2026-06-01"          # a Monday
SUN = "2026-06-07"


def _ts(date: str, hour_after_start: float) -> int:
    """Epoch ``hour_after_start`` hours after the local day start (04:00)."""
    return day_bounds(date, TZ, DSH)[0] + int(hour_after_start * 3600)


def _span(conn, date: str, hour: float, minutes: int, cat_id, kind="app", **kw):
    lo = _ts(date, hour)
    dbmod.insert_span(conn, {
        "start_ts": lo, "end_ts": lo + minutes * 60, "kind": kind,
        "exe": kw.get("exe"), "app_name": None, "window_title": None,
        "url": None, "domain": kw.get("domain"), "detail": None,
        "category_id": cat_id, "project_id": kw.get("project_id"),
        "classified_by": "rule" if cat_id else None,
        "rule_id": None, "ai_confidence": None, "edited": 0,
    })


def _goal(conn, *, name="G", period="daily", direction="at_least", target=60,
          cat_id=None, project_id=None, active_days=None, created: str = MON) -> dict:
    cur = conn.execute(
        "INSERT INTO goals(name, period, direction, target_minutes, category_id, "
        "project_id, active_days, created_ts) VALUES(?,?,?,?,?,?,?,?)",
        (name, period, direction, target, cat_id, project_id,
         json.dumps(active_days) if active_days else None, _ts(created, 0)),
    )
    return dict(conn.execute("SELECT * FROM goals WHERE id=?", (cur.lastrowid,)).fetchone())


def _cat(conn, name: str) -> int:
    return conn.execute("SELECT id FROM categories WHERE name=?", (name,)).fetchone()["id"]


# --- period math ---------------------------------------------------------------
def test_period_math():
    assert goals.period_start_of("2026-06-03", "daily") == "2026-06-03"
    assert goals.period_start_of("2026-06-03", "weekly") == "2026-06-01"   # Wed -> Mon
    assert goals.period_start_of("2026-06-07", "weekly") == "2026-06-01"   # Sun stays in week
    assert goals.period_start_of("2026-06-15", "monthly") == "2026-06-01"
    assert goals.period_start_of("2026-06-15", "yearly") == "2026-01-01"
    assert goals.next_period_start("2026-06-01", "weekly") == "2026-06-08"
    assert goals.next_period_start("2026-12-01", "monthly") == "2027-01-01"
    assert goals.prev_period_start("2026-01-01", "monthly") == "2025-12-01"
    assert goals.prev_period_start("2026-01-01", "yearly") == "2025-01-01"


def test_weekly_bounds_span_mon_to_sun(db):
    lo, hi = goals.period_bounds("2026-06-01", "weekly", TZ, DSH)
    assert lo == day_bounds("2026-06-01", TZ, DSH)[0]        # Monday 04:00
    assert hi == day_bounds("2026-06-08", TZ, DSH)[0]        # next Monday 04:00
    assert hi - lo == 7 * 86400


# --- goal_minutes: clipping, manual spans, project filter ------------------------
def test_minutes_clip_across_day_boundary(db):
    cid = _cat(db, "Placements")
    # 03:00–05:00 local on Jun 3 = crosses the 04:00 day boundary:
    # one hour belongs to Jun 2, one hour to Jun 3.
    start = day_bounds("2026-06-03", TZ, DSH)[0] - 3600
    dbmod.insert_span(db, {
        "start_ts": start, "end_ts": start + 7200, "kind": "app", "exe": None,
        "app_name": None, "window_title": None, "url": None, "domain": None,
        "detail": None, "category_id": cid, "project_id": None,
        "classified_by": "rule", "rule_id": None, "ai_confidence": None, "edited": 0,
    })
    g = _goal(db, cat_id=cid)
    for date, want in (("2026-06-02", 60), ("2026-06-03", 60)):
        lo, hi = goals.period_bounds(date, "daily", TZ, DSH)
        assert goals.goal_minutes(db, g, lo, hi) == want


def test_minutes_count_manual_but_not_idle(db):
    cid = _cat(db, "Placements")
    _span(db, "2026-06-03", 2, 90, cid, kind="manual")     # offline prep counts
    _span(db, "2026-06-03", 5, 120, cid, kind="idle")      # idle never counts, even categorized
    g = _goal(db, cat_id=cid, target=180)
    lo, hi = goals.period_bounds("2026-06-03", "daily", TZ, DSH)
    assert goals.goal_minutes(db, g, lo, hi) == 90


def test_minutes_project_goal_filters_by_project(db):
    cid = _cat(db, "Agency (DevsCrest)")
    pid = db.execute("INSERT INTO projects(category_id, name) VALUES(?, 'LAWFIRM')",
                     (cid,)).lastrowid
    _span(db, "2026-06-03", 2, 60, cid, project_id=pid)
    _span(db, "2026-06-03", 4, 60, cid)                    # same category, no project
    g = _goal(db, cat_id=None, project_id=pid)
    lo, hi = goals.period_bounds("2026-06-03", "daily", TZ, DSH)
    assert goals.goal_minutes(db, g, lo, hi) == 60


# --- acceptance: the two PRD daily goals -----------------------------------------
def test_prd_daily_goals_compute_correctly(db):
    plc, ent = _cat(db, "Placements"), _cat(db, "Entertainment")
    date = "2026-06-03"
    _span(db, date, 2, 100, plc)
    _span(db, date, 6, 85, plc, kind="manual")             # manual spans count
    _span(db, date, 10, 100, ent)
    g_plc = _goal(db, name=">=3h Placements", direction="at_least", target=180, cat_id=plc)
    g_ent = _goal(db, name="<=1.5h Entertainment", direction="at_most", target=90, cat_id=ent)
    ev_p = goals.evaluate(db, CFG, g_plc, date)
    ev_e = goals.evaluate(db, CFG, g_ent, date)
    assert (ev_p["minutes"], ev_p["met"]) == (185, True)
    assert (ev_e["minutes"], ev_e["met"]) == (100, False)  # over the cap


def test_weekly_goal_spans_mon_sun(db):
    cid = _cat(db, "Agency (DevsCrest)")
    _span(db, MON, 2, 60, cid)                             # Monday
    _span(db, SUN, 2, 61, cid)                             # Sunday, same week
    # 02:00 local next Monday = before 04:00 cutoff -> still Sunday -> in week
    _span(db, SUN, 22, 30, cid)
    _span(db, "2026-06-08", 5, 500, cid)                   # next week: excluded
    g = _goal(db, period="weekly", target=120, cat_id=cid)
    ev = goals.evaluate(db, CFG, g, "2026-06-01")
    assert ev["minutes"] == 151
    assert ev["met"] is True


# --- streaks ---------------------------------------------------------------------
def test_streak_at_least_basic(db):
    cid = _cat(db, "Placements")
    g = _goal(db, cat_id=cid, target=60, created=MON)
    # Mon..Wed met, Thu missed, Fri+Sat met, Sun = "today" with no data yet
    for d in ("2026-06-01", "2026-06-02", "2026-06-03", "2026-06-05", "2026-06-06"):
        _span(db, d, 2, 60, cid)
    st = goals.streaks(db, CFG, g, today=SUN)
    assert st == {"current": 2, "best": 3}   # pending Sunday neither breaks nor extends

    # meeting it today extends the streak immediately
    _span(db, SUN, 2, 60, cid)
    db.execute("DELETE FROM goal_progress")  # drop cache: spans changed
    st = goals.streaks(db, CFG, g, today=SUN)
    assert st == {"current": 3, "best": 3}


def test_streak_at_most_break_is_irreversible_today(db):
    ent = _cat(db, "Entertainment")
    g = _goal(db, name="cap", direction="at_most", target=90, cat_id=ent, created=MON)
    # Mon..Fri under cap (incl. zero-time days), Sat = today, already over cap
    _span(db, "2026-06-02", 10, 30, ent)
    _span(db, "2026-06-06", 10, 120, ent)
    st = goals.streaks(db, CFG, g, today="2026-06-06")
    assert st == {"current": 0, "best": 5}   # blowing the cap today breaks NOW


def test_streak_skips_inactive_days(db):
    cid = _cat(db, "Placements")
    # weekdays-only goal: Sat/Sun are skipped — neither break nor extend
    g = _goal(db, cat_id=cid, target=60, active_days=[0, 1, 2, 3, 4], created=MON)
    for d in ("2026-06-04", "2026-06-05", "2026-06-08"):   # Thu, Fri, next Mon
        _span(db, d, 2, 60, cid)
    # Mon..Wed missed -> then Thu+Fri met, weekend skipped, Mon met
    st = goals.streaks(db, CFG, g, today="2026-06-08")
    assert st == {"current": 3, "best": 3}   # streak survives the weekend


def test_streak_counts_from_creation_only(db):
    cid = _cat(db, "Placements")
    _span(db, "2026-06-01", 2, 60, cid)                    # before creation: ignored
    g = _goal(db, cat_id=cid, target=60, created="2026-06-03")
    _span(db, "2026-06-03", 2, 60, cid)
    _span(db, "2026-06-04", 2, 60, cid)
    st = goals.streaks(db, CFG, g, today="2026-06-04")
    assert st == {"current": 2, "best": 2}


# --- cache: write-through, invalidation, rollup ------------------------------------
def test_evaluate_caches_closed_periods(db):
    cid = _cat(db, "Placements")
    g = _goal(db, cat_id=cid, target=60)
    _span(db, "2026-06-03", 2, 90, cid)
    goals.evaluate(db, CFG, g, "2026-06-03")
    row = db.execute("SELECT minutes, met FROM goal_progress WHERE goal_id=? AND period_start=?",
                     (g["id"], "2026-06-03")).fetchone()
    assert (row["minutes"], row["met"]) == (90, 1)
    # cache wins even if spans change silently...
    _span(db, "2026-06-03", 8, 60, cid)
    assert goals.evaluate(db, CFG, g, "2026-06-03")["minutes"] == 90
    # ...until the edit path invalidates the touched periods
    goals.invalidate_progress(db, CFG, _ts("2026-06-03", 8), _ts("2026-06-03", 9))
    assert goals.evaluate(db, CFG, g, "2026-06-03")["minutes"] == 150


def test_rollup_backfills_closed_periods(db):
    cid = _cat(db, "Placements")
    g = _goal(db, cat_id=cid, target=60, created=MON)
    _span(db, "2026-06-01", 2, 60, cid)
    _span(db, "2026-06-02", 2, 30, cid)
    n = goals.rollup(db, CFG)
    assert n > 0
    rows = {r["period_start"]: r for r in db.execute(
        "SELECT * FROM goal_progress WHERE goal_id=?", (g["id"],))}
    assert rows["2026-06-01"]["met"] == 1
    assert rows["2026-06-02"]["met"] == 0


# --- API-facing shapes --------------------------------------------------------------
def test_goal_card_shape_and_history(db):
    cid = _cat(db, "Placements")
    g = _goal(db, cat_id=cid, target=60, created=MON)
    _span(db, MON, 2, 90, cid)
    card = goals.goal_card(db, CFG, g, today="2026-06-03")
    assert card["period"] == "daily" and card["direction"] == "at_least"
    assert card["streak"] == {"current": 0, "best": 1}     # Tue missed broke it
    assert [h["status"] for h in card["history"]] == ["met", "missed", "pending"]
    assert len(card["history"]) <= goals.HISTORY_LEN["daily"]


def test_goals_for_day_streak_and_active_flag(db):
    cid = _cat(db, "Placements")
    _goal(db, cat_id=cid, target=60, active_days=[0, 1, 2, 3, 4], created=MON)
    _span(db, "2026-06-05", 2, 60, cid)                    # Friday met
    out = goals.goals_for_day(db, CFG, "2026-06-06")       # Saturday: inactive
    assert len(out) == 1
    assert out[0]["active_today"] is False
    assert out[0]["streak"] == 1
