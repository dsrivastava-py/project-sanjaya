"""Reporting + journal + weekly-insight tests (PRD §8.6, §9.3, §13.8, Phase 5).

The Groq endpoint is never touched — a fake narrative client returns canned JSON.
Includes the §15 'no invented activity' heuristic and the midnight-split rule.
"""
from __future__ import annotations

import json

import pytest

from sanjaya import config as configmod, db as dbmod, reporting
from sanjaya.ai import jobs, prompts
from sanjaya.timeutil import day_bounds

DATE = "2026-07-10"


@pytest.fixture()
def cfg():
    return configmod.load(create=False)


class FakeNarr:
    def __init__(self, data, *, boom=False):
        self._data = data
        self._boom = boom
        self.calls: list[dict] = []

    def complete(self, conn, *, kind, model, system, user, json_mode=True, temperature=0.5):
        self.calls.append({"kind": kind, "system": system, "user": user})
        if self._boom:
            raise AssertionError("client must not be called")
        return {"data": self._data, "text": "", "total_tokens": 10}


def _lo(cfg):
    return day_bounds(DATE, cfg.timezone, cfg.day_start_hour)[0]


def _span(conn, start, end, kind, cat=None, *, exe="chrome.exe", app="Google Chrome",
          domain=None, detail=None, title=""):
    cid = None
    if cat:
        cid = conn.execute("SELECT id FROM categories WHERE name=?", (cat,)).fetchone()["id"]
    return dbmod.insert_span(conn, {
        "start_ts": start, "end_ts": end, "kind": kind, "exe": exe, "app_name": app,
        "window_title": title, "url": None, "domain": domain, "detail": detail,
        "category_id": cid, "project_id": None,
        "classified_by": "rule" if cid else None, "rule_id": None,
        "ai_confidence": None, "edited": 0,
    })


def _seed_day(db, cfg):
    lo = _lo(cfg)
    _span(db, lo + 3600, lo + 7200, "code", "Building (own products)",
          exe="code.exe", app="VS Code", detail={"file": "main.py", "project_dir": "sanjaya"})
    _span(db, lo + 7200, lo + 9000, "web", "Placements",
          domain="linkedin.com", detail={"page_title": "Jobs"})
    _span(db, lo + 9000, lo + 10200, "youtube", "Entertainment",
          domain="youtube.com", detail={"video_title": "Funny Cats", "channel": "CatTV"})
    _span(db, lo + 10200, lo + 10800, "idle")
    return lo


# --- deterministic day payload ----------------------------------------------
def test_day_payload_totals_and_focus(db, cfg):
    _seed_day(db, cfg)
    p = reporting.build_day_payload(db, cfg, DATE)
    assert p["active_seconds"] == 3600 + 1800 + 1200
    assert p["idle_seconds"] == 600
    assert p["has_activity"] is True
    assert 0 <= p["focus_score"] <= 100
    # category totals present, sorted by size (Building biggest)
    assert "Building (own products)" in p["category_totals"]
    assert "Placements" in p["category_totals"]
    assert "Funny Cats" in p["timeline"]
    assert p["weekday"] == "Friday"


def test_midnight_span_clipped_to_day(db, cfg):
    lo = _lo(cfg)
    _span(db, lo - 1000, lo + 1000, "app", "College", exe="winword.exe")  # straddles start
    p = reporting.build_day_payload(db, cfg, DATE)
    assert p["active_seconds"] == 1000  # only the in-day half counts (§13.8)


# --- quiet day (no AI) -------------------------------------------------------
def test_quiet_day_no_ai_call(db, cfg):
    client = FakeNarr(None, boom=True)
    res = jobs.summarize_day(db, client, cfg, DATE)
    assert res["status"] == "quiet"
    assert client.calls == []                       # AI never called
    row = db.execute("SELECT narrative_md, focus_score, ai_model FROM day_summaries WHERE date=?",
                     (DATE,)).fetchone()
    assert row["narrative_md"] == jobs.QUIET_DAY_MD
    assert row["focus_score"] == 0.0                # deterministic focus persisted
    assert row["ai_model"] is None


# --- generated journal + honesty --------------------------------------------
def test_generated_journal_persists_and_is_honest(db, cfg):
    _seed_day(db, cfg)
    narrative = ("You spent the morning deep in Building work on main.py, then "
                 "pivoted to Placements. You unwound with Funny Cats.")
    client = FakeNarr({"narrative_md": narrative,
                       "highlights": ["Shipped Building progress", "Applied via Placements"],
                       "suggestions": ["Start earlier tomorrow"]})
    res = jobs.summarize_day(db, client, cfg, DATE, force=True)
    assert res["status"] == "generated"

    row = db.execute("SELECT * FROM day_summaries WHERE date=?", (DATE,)).fetchone()
    assert row["narrative_md"] == narrative
    assert json.loads(row["highlights"]) == ["Shipped Building progress", "Applied via Placements"]
    assert row["ai_model"] == cfg.get("ai", "narrative_model")
    assert row["edited"] == 0
    assert row["focus_score"] is not None

    # §15 heuristic: every proper noun in the narrative appears in the payload
    _, user = prompts.daily_journal(res["payload"])
    assert reporting.hallucinated_nouns(narrative, user) == set()


def test_hallucination_heuristic_flags_invented_nouns(db, cfg):
    _seed_day(db, cfg)
    _, user = prompts.daily_journal(reporting.build_day_payload(db, cfg, DATE))
    bad = "You binged Netflix and studied Calculus with ProfessorX."
    flagged = reporting.hallucinated_nouns(bad, user)
    assert "Netflix" in flagged and "Calculus" in flagged


# --- regenerate preserves the user's note -----------------------------------
def test_regenerate_overwrites_narrative_keeps_user_note(db, cfg):
    _seed_day(db, cfg)
    jobs.summarize_day(db, FakeNarr({"narrative_md": "v1", "highlights": [], "suggestions": []}),
                       cfg, DATE, force=True)
    db.execute("UPDATE day_summaries SET user_note_md=? WHERE date=?", ("my private note", DATE))

    jobs.summarize_day(db, FakeNarr({"narrative_md": "v2", "highlights": [], "suggestions": []}),
                       cfg, DATE, force=True)
    row = db.execute("SELECT narrative_md, user_note_md FROM day_summaries WHERE date=?",
                     (DATE,)).fetchone()
    assert row["narrative_md"] == "v2"
    assert row["user_note_md"] == "my private note"


def test_existing_narrative_not_regenerated_without_force(db, cfg):
    _seed_day(db, cfg)
    jobs.summarize_day(db, FakeNarr({"narrative_md": "keep me", "highlights": [], "suggestions": []}),
                       cfg, DATE, force=True)
    res = jobs.summarize_day(db, FakeNarr(None, boom=True), cfg, DATE)  # boom if it calls AI
    assert res["status"] == "exists"


# --- 3-day honesty spot-check (Phase 5 acceptance) ---------------------------
def test_three_test_days_no_hallucinated_activities(db, cfg):
    """Phase 5 ✅: journals across 3 distinct test days reference only real data."""
    days = {
        "2026-07-07": [("code", "Building (own products)", {"file": "api.py", "project_dir": "sanjaya"}, "code.exe"),
                       ("web", "Placements", {"page_title": "Naukri Jobs"}, "chrome.exe")],
        "2026-07-08": [("doc", "College", {"file": "Thermodynamics.docx", "app": "Word"}, "winword.exe"),
                       ("youtube", "Entertainment", {"video_title": "Lofi Beats", "channel": "ChillHop"}, "chrome.exe")],
        "2026-07-09": [("ai_chat", "Dual Degree", {"topic": "Statistics assignment help"}, "chrome.exe"),
                       ("search", "Personal Growth", {"query": "habit stacking"}, "chrome.exe")],
    }
    narratives = {
        "2026-07-07": "You worked on api.py in the sanjaya project, then browsed Naukri Jobs for Placements.",
        "2026-07-08": "You wrote Thermodynamics.docx for College and relaxed with Lofi Beats by ChillHop.",
        "2026-07-09": "You got Statistics assignment help via AI chat and read about habit stacking.",
    }
    for date, items in days.items():
        lo = day_bounds(date, cfg.timezone, cfg.day_start_hour)[0]
        t = lo + 3600
        for kind, cat, detail, exe in items:
            _span(db, t, t + 1800, kind, cat, exe=exe, detail=detail)
            t += 1800
        res = jobs.summarize_day(
            db, FakeNarr({"narrative_md": narratives[date], "highlights": [], "suggestions": []}),
            cfg, date, force=True)
        assert res["status"] == "generated"
        _, user = prompts.daily_journal(res["payload"])
        assert reporting.hallucinated_nouns(narratives[date], user) == set(), date


# --- weekly insight ----------------------------------------------------------
def test_weekly_insight_caches_to_settings(db, cfg):
    ws = reporting.week_start_of(DATE)
    data = {"insight_md": "A solid week of Building.", "wins": ["shipped"],
            "leaks": [], "next_week_focus": ["more Placements"]}
    rec = jobs.weekly_insight(db, FakeNarr(data), cfg, ws, force=True)
    assert rec["insight_md"] == "A solid week of Building."
    cached = json.loads(dbmod.get_setting(db, f"weekly_{ws}"))
    assert cached["wins"] == ["shipped"]
    assert cached["week_start"] == ws
