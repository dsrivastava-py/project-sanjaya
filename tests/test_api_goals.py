"""HTTP tests for the Phase 8 goals surface: CRUD /api/goals, /api/goals/progress,
day-view goal meters (incl. manual spans + day-boundary honesty), archive
semantics, and the goal_progress cache invalidation on edits. Temp DB, no network.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sanjaya import config as configmod, db as dbmod, paths
from sanjaya.runtime import RuntimeState
from sanjaya.server.app import create_app
from sanjaya.timeutil import day_bounds

DATE = "2026-07-08"          # a Wednesday
WEEK_MON = "2026-07-06"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DB_PATH", tmp_path / "api.db")
    dbmod.init_db()
    cfg = configmod.load(create=False)
    app = create_app(cfg, RuntimeState(), controller=None)
    return TestClient(app), cfg


def _cat_id(name: str) -> int:
    conn = dbmod.connect()
    cid = conn.execute("SELECT id FROM categories WHERE name=?", (name,)).fetchone()["id"]
    conn.close()
    return cid


def _mk_span(cfg, date: str, hour: float, minutes: int, cat, *, kind="app"):
    conn = dbmod.connect()
    lo = day_bounds(date, cfg.timezone, cfg.day_start_hour)[0] + int(hour * 3600)
    sid = dbmod.insert_span(conn, {
        "start_ts": lo, "end_ts": lo + minutes * 60, "kind": kind, "exe": None,
        "app_name": None, "window_title": None, "url": None, "domain": None,
        "detail": None, "category_id": cat, "project_id": None,
        "classified_by": "rule" if cat else None, "rule_id": None,
        "ai_confidence": None, "edited": 0,
    })
    conn.close()
    return sid


def _backdate(goal_id: int, cfg, date: str) -> None:
    """Move a goal's creation to ``date`` so past periods count for streaks."""
    conn = dbmod.connect()
    conn.execute("UPDATE goals SET created_ts=? WHERE id=?",
                 (day_bounds(date, cfg.timezone, cfg.day_start_hour)[0], goal_id))
    conn.close()


# --- CRUD + validation -----------------------------------------------------------
def test_create_goal_validation(client):
    c, _ = client
    plc = _cat_id("Placements")
    base = {"name": "G", "period": "daily", "direction": "at_least",
            "target_minutes": 60, "category_id": plc}
    assert c.post("/api/goals", json=base).status_code == 200
    assert c.post("/api/goals", json={**base, "name": " "}).status_code == 422
    assert c.post("/api/goals", json={**base, "period": "fortnightly"}).status_code == 422
    assert c.post("/api/goals", json={**base, "direction": "exactly"}).status_code == 422
    assert c.post("/api/goals", json={**base, "target_minutes": "many"}).status_code == 422
    assert c.post("/api/goals", json={**base, "category_id": None}).status_code == 422
    assert c.post("/api/goals", json={**base, "category_id": 9999}).status_code == 422
    assert c.post("/api/goals", json={**base, "active_days": []}).status_code == 422
    assert c.post("/api/goals", json={**base, "active_days": [7]}).status_code == 422
    assert c.post("/api/goals", json={**base, "period": "weekly",
                                      "active_days": [0, 1]}).status_code == 422
    # project XOR category
    pid = c.post("/api/projects", json={"name": "P", "category_id": plc}).json()["project"]["id"]
    assert c.post("/api/goals", json={**base, "project_id": pid}).status_code == 422
    r = c.post("/api/goals", json={**base, "category_id": None, "project_id": pid})
    assert r.status_code == 200
    assert r.json()["goal"]["project_id"] == pid


def test_goal_card_fields(client):
    c, _ = client
    r = c.post("/api/goals", json={"name": "≥3h Placements", "period": "daily",
                                   "direction": "at_least", "target_minutes": 180,
                                   "category_id": _cat_id("Placements"),
                                   "active_days": [0, 1, 2, 3, 4]})
    g = r.json()["goal"]
    assert g["direction"] == "at_least" and g["target_minutes"] == 180
    assert g["active_days"] == [0, 1, 2, 3, 4]
    assert set(g["streak"]) == {"current", "best"}
    assert isinstance(g["history"], list)
    assert g["status"] in ("met", "missed", "pending", "skipped")


# --- acceptance: PRD daily goals via the API -----------------------------------------
def test_prd_goals_across_boundary_and_manual(client):
    c, cfg = client
    plc, ent = _cat_id("Placements"), _cat_id("Entertainment")
    lo = day_bounds(DATE, cfg.timezone, cfg.day_start_hour)[0]

    # placements: 2h tracked + 1h manual + a boundary-crossing span
    _mk_span(cfg, DATE, 2, 120, plc)
    _mk_span(cfg, DATE, 6, 60, plc, kind="manual")
    conn = dbmod.connect()   # 03:30–04:30 local: only 30 min belong to DATE
    dbmod.insert_span(conn, {
        "start_ts": lo - 1800, "end_ts": lo + 1800, "kind": "app", "exe": None,
        "app_name": None, "window_title": None, "url": None, "domain": None,
        "detail": None, "category_id": plc, "project_id": None,
        "classified_by": "rule", "rule_id": None, "ai_confidence": None, "edited": 0,
    })
    conn.close()
    _mk_span(cfg, DATE, 12, 80, ent)

    g1 = c.post("/api/goals", json={"name": "≥3h Placements", "period": "daily",
                                    "direction": "at_least", "target_minutes": 180,
                                    "category_id": plc}).json()["goal"]
    g2 = c.post("/api/goals", json={"name": "≤1.5h Entertainment", "period": "daily",
                                    "direction": "at_most", "target_minutes": 90,
                                    "category_id": ent}).json()["goal"]
    _backdate(g1["id"], cfg, "2026-07-01")
    _backdate(g2["id"], cfg, "2026-07-01")

    goals = {g["name"]: g for g in c.get(f"/api/day/{DATE}").json()["goals"]}
    plc_g, ent_g = goals["≥3h Placements"], goals["≤1.5h Entertainment"]
    assert plc_g["minutes"] == 210          # 120 + 60 manual + 30 clipped
    assert plc_g["met"] is True
    assert ent_g["minutes"] == 80
    assert ent_g["met"] is True             # under the cap
    assert "streak" in plc_g and "best_streak" in plc_g

    r = c.get("/api/goals/progress", params={"period": "daily", "date": DATE}).json()
    assert r["period_start"] == DATE
    by_id = {g["goal_id"]: g for g in r["goals"]}
    assert by_id[g1["id"]]["minutes"] == 210 and by_id[g1["id"]]["met"] is True


def test_weekly_goal_progress_mon_sun(client):
    c, cfg = client
    agency = _cat_id("Agency (DevsCrest)")
    _mk_span(cfg, WEEK_MON, 2, 300, agency)               # Monday 5h
    _mk_span(cfg, "2026-07-12", 2, 300, agency)           # Sunday 5h
    _mk_span(cfg, "2026-07-13", 5, 600, agency)           # next Monday: out
    g = c.post("/api/goals", json={"name": "20h Agency weekly", "period": "weekly",
                                   "direction": "at_least", "target_minutes": 1200,
                                   "category_id": agency}).json()["goal"]
    _backdate(g["id"], cfg, "2026-06-01")
    r = c.get("/api/goals/progress", params={"period": "weekly", "date": DATE}).json()
    assert r["period_start"] == WEEK_MON
    got = {x["goal_id"]: x for x in r["goals"]}[g["id"]]
    assert got["minutes"] == 600
    assert got["met"] is False                            # 10h of 20h


# --- edit invalidation, patch, archive ------------------------------------------------
def test_span_edit_invalidates_goal_cache(client):
    c, cfg = client
    plc = _cat_id("Placements")
    g = c.post("/api/goals", json={"name": "G", "period": "daily",
                                   "direction": "at_least", "target_minutes": 60,
                                   "category_id": plc}).json()["goal"]
    _backdate(g["id"], cfg, "2026-07-01")
    sid = _mk_span(cfg, DATE, 2, 90, None)

    r = c.get("/api/goals/progress", params={"period": "daily", "date": DATE}).json()
    assert r["goals"][0]["minutes"] == 0                  # uncategorized: no credit

    c.patch(f"/api/spans/{sid}", json={"category_id": plc})
    r = c.get("/api/goals/progress", params={"period": "daily", "date": DATE}).json()
    assert r["goals"][0]["minutes"] == 90                 # cache dropped, recomputed
    assert r["goals"][0]["met"] is True


def test_patch_goal_recomputes_and_audits(client):
    c, cfg = client
    plc = _cat_id("Placements")
    _mk_span(cfg, DATE, 2, 90, plc)
    g = c.post("/api/goals", json={"name": "G", "period": "daily",
                                   "direction": "at_least", "target_minutes": 60,
                                   "category_id": plc}).json()["goal"]
    _backdate(g["id"], cfg, "2026-07-01")
    assert c.get("/api/goals/progress", params={"period": "daily", "date": DATE}
                 ).json()["goals"][0]["met"] is True

    r = c.patch(f"/api/goals/{g['id']}", json={"target_minutes": 120})
    assert r.status_code == 200
    assert r.json()["goal"]["target_minutes"] == 120
    assert c.get("/api/goals/progress", params={"period": "daily", "date": DATE}
                 ).json()["goals"][0]["met"] is False      # verdict flipped with target

    conn = dbmod.connect()
    n = conn.execute("SELECT COUNT(*) c FROM edits_audit WHERE entity='goal' "
                     "AND field='target_minutes'").fetchone()["c"]
    conn.close()
    assert n == 1


def test_archive_goal(client):
    c, _ = client
    g = c.post("/api/goals", json={"name": "G", "period": "daily",
                                   "direction": "at_least", "target_minutes": 60,
                                   "category_id": _cat_id("Placements")}).json()["goal"]
    assert c.delete(f"/api/goals/{g['id']}").status_code == 200
    assert c.get("/api/goals").json()["goals"] == []
    archived = c.get("/api/goals", params={"include_archived": True}).json()["goals"]
    assert len(archived) == 1 and archived[0]["archived"] is True
    assert c.delete("/api/goals/999").status_code == 404
