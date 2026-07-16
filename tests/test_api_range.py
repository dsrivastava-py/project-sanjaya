"""HTTP tests for the Phase 6 read endpoints: /api/range, /api/categories, and
the structured goals list in /api/day. Temp DB, no network."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sanjaya import config as configmod, db as dbmod, paths
from sanjaya.runtime import RuntimeState
from sanjaya.server.app import create_app
from sanjaya.timeutil import day_bounds

D1, D2, D3 = "2026-07-08", "2026-07-09", "2026-07-10"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DB_PATH", tmp_path / "range.db")
    dbmod.init_db()
    cfg = configmod.load(create=False)
    app = create_app(cfg, RuntimeState(), controller=None)
    return TestClient(app), cfg


def _cat(name: str) -> int:
    conn = dbmod.connect()
    cid = conn.execute("SELECT id FROM categories WHERE name=?", (name,)).fetchone()["id"]
    conn.close()
    return cid


def _span(cfg, date: str, hour: int, dur_s: int, kind: str, cat_id, exe="chrome.exe"):
    conn = dbmod.connect()
    lo = day_bounds(date, cfg.timezone, cfg.day_start_hour)[0]
    dbmod.insert_span(conn, {
        "start_ts": lo + hour * 3600, "end_ts": lo + hour * 3600 + dur_s,
        "kind": kind, "exe": exe, "app_name": None, "window_title": "t",
        "url": None, "domain": None, "detail": None,
        "category_id": cat_id, "project_id": None, "classified_by": "rule",
        "rule_id": None, "ai_confidence": None, "edited": 0,
    })
    conn.close()


def test_categories_endpoint_seeds(client):
    c, _ = client
    cats = c.get("/api/categories").json()["categories"]
    assert len(cats) == 8
    slots = [x["color_slot"] for x in cats]
    assert slots == [1, 2, 3, 4, 5, 6, 7, 8]          # §4.3 fixed slot order
    assert cats[0]["name"] == "Agency (DevsCrest)"


def test_range_daily_aggregates(client):
    c, cfg = client
    placements = _cat("Placements")
    ent = _cat("Entertainment")
    _span(cfg, D1, 6, 3600, "web", placements)
    _span(cfg, D1, 8, 1800, "idle", None)
    _span(cfg, D2, 7, 7200, "youtube", ent)

    days = c.get("/api/range", params={"from": D1, "to": D3}).json()["days"]
    assert [d["date"] for d in days] == [D1, D2, D3]
    assert days[0]["active_seconds"] == 3600
    assert days[0]["idle_seconds"] == 1800
    assert days[0]["category_totals"] == {str(placements): 3600}
    assert days[1]["category_totals"] == {str(ent): 7200}
    assert days[2]["active_seconds"] == 0
    assert days[2]["focus_score"] is None            # empty day → honest gap, no score


def test_range_validation(client):
    c, _ = client
    assert c.get("/api/range", params={"from": "bad", "to": D1}).status_code == 422
    assert c.get("/api/range", params={"from": D2, "to": D1}).status_code == 422
    assert c.get("/api/range", params={"from": "2020-01-01", "to": "2026-01-01"}).status_code == 422
    assert c.get("/api/range", params={"from": D1, "to": D1, "bucket": "week"}).status_code == 422


def test_time_leaks_week_over_week(client):
    c, cfg = client
    ent = _cat("Entertainment")
    placements = _cat("Placements")
    # D1..D3 fall in the week of Mon 2026-07-06; previous week = 2026-06-29..
    conn = dbmod.connect()

    def spn(date, hour, dur, cat, domain):
        lo = day_bounds(date, cfg.timezone, cfg.day_start_hour)[0]
        dbmod.insert_span(conn, {
            "start_ts": lo + hour * 3600, "end_ts": lo + hour * 3600 + dur,
            "kind": "web", "exe": "chrome.exe", "app_name": None, "window_title": "t",
            "url": None, "domain": domain, "detail": None,
            "category_id": cat, "project_id": None, "classified_by": "rule",
            "rule_id": None, "ai_confidence": None, "edited": 0,
        })

    spn(D1, 6, 7200, ent, "youtube.com")          # this week: 2h
    spn("2026-07-01", 6, 3600, ent, "youtube.com")  # prev week: 1h
    spn(D2, 7, 1800, None, "notion.so")           # uncategorized leak, new
    spn(D2, 9, 3600, placements, "linkedin.com")  # productive → NOT a leak
    conn.close()

    r = c.get("/api/insights/leaks", params={"week": D1}).json()
    assert r["week_start"] == "2026-07-06"
    by_dom = {x["domain"]: x for x in r["leaks"]}
    assert by_dom["youtube.com"]["this_s"] == 7200
    assert by_dom["youtube.com"]["prev_s"] == 3600
    assert by_dom["youtube.com"]["delta_s"] == 3600
    assert by_dom["notion.so"]["delta_s"] == 1800
    assert "linkedin.com" not in by_dom


def test_day_includes_structured_goals(client):
    c, cfg = client
    placements = _cat("Placements")
    conn = dbmod.connect()
    conn.execute(
        "INSERT INTO goals(name, period, direction, target_minutes, category_id, created_ts) "
        "VALUES('≥3h Placements','daily','at_least',180,?,0)", (placements,))
    conn.commit()
    conn.close()
    _span(cfg, D1, 6, 4 * 3600, "web", placements)

    goals = c.get(f"/api/day/{D1}").json()["goals"]
    assert len(goals) == 1
    g = goals[0]
    assert g["name"] == "≥3h Placements"
    assert g["minutes"] == 240 and g["target_minutes"] == 180
    assert g["met"] is True

    # at_most direction
    conn = dbmod.connect()
    conn.execute("UPDATE goals SET direction='at_most', target_minutes=90")
    conn.commit()
    conn.close()
    g = c.get(f"/api/day/{D1}").json()["goals"][0]
    assert g["met"] is False
