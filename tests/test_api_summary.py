"""HTTP-level tests for the Phase 5 API surface: /api/day, /api/summary
read/edit/regenerate, /api/insights/weekly. Runs against a temp DB (paths.DB_PATH
monkeypatched) with GroqClient replaced by a fake — no network, no real data dir.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from sanjaya import config as configmod, db as dbmod, paths
from sanjaya.runtime import RuntimeState
from sanjaya.server import api as apimod
from sanjaya.server.app import create_app
from sanjaya.timeutil import day_bounds

DATE = "2026-07-10"


class FakeGroq:
    def __init__(self, cfg=None, **kw):
        pass

    def complete(self, conn, *, kind, model, system, user, json_mode=True, temperature=0.5):
        data = {"narrative_md": "You focused on Building today.",
                "highlights": ["Shipped a feature"], "suggestions": ["Sleep earlier"]}
        if kind == "weekly_insight":
            data = {"insight_md": "Steady week.", "wins": ["consistency"],
                    "leaks": [], "next_week_focus": ["Placements"]}
        return {"data": data, "text": "", "total_tokens": 5}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DB_PATH", tmp_path / "api.db")
    monkeypatch.setattr(apimod, "GroqClient", FakeGroq)
    dbmod.init_db()
    cfg = configmod.load(create=False)
    app = create_app(cfg, RuntimeState(), controller=None)
    return TestClient(app), cfg


def _seed(cfg):
    conn = dbmod.connect()
    lo = day_bounds(DATE, cfg.timezone, cfg.day_start_hour)[0]
    cid = conn.execute("SELECT id FROM categories WHERE name='Building (own products)'"
                       ).fetchone()["id"]
    dbmod.insert_span(conn, {
        "start_ts": lo + 3600, "end_ts": lo + 7200, "kind": "code", "exe": "code.exe",
        "app_name": "VS Code", "window_title": "main.py — sanjaya — Visual Studio Code",
        "url": None, "domain": None, "detail": {"file": "main.py"},
        "category_id": cid, "project_id": None, "classified_by": "rule",
        "rule_id": None, "ai_confidence": None, "edited": 0,
    })
    conn.close()


def test_day_endpoint_deterministic(client):
    c, cfg = client
    _seed(cfg)
    d = c.get(f"/api/day/{DATE}").json()
    assert d["active_seconds"] == 3600
    assert len(d["spans"]) == 1
    assert d["summary"]["exists"] is False       # AI absence never blanks the UI (§13.6)


def test_generate_then_read_then_edit_summary(client):
    c, cfg = client
    _seed(cfg)
    # regenerate endpoint works (Phase 5 ✅)
    r = c.post(f"/api/summary/{DATE}/generate")
    assert r.status_code == 200
    assert r.json()["narrative_md"] == "You focused on Building today."
    assert r.json()["edited"] is False

    # read
    r = c.get(f"/api/summary/{DATE}")
    assert r.json()["highlights"] == ["Shipped a feature"]

    # edit -> edited flag + audit row
    r = c.patch(f"/api/summary/{DATE}", json={"narrative_md": "My own words."})
    assert r.json()["narrative_md"] == "My own words."
    assert r.json()["edited"] is True
    conn = dbmod.connect()
    n = conn.execute("SELECT COUNT(*) c FROM edits_audit WHERE entity='summary'").fetchone()["c"]
    conn.close()
    assert n == 1


def test_quiet_day_via_endpoint(client):
    c, _ = client
    r = c.post("/api/summary/2026-01-01/generate")   # no spans that day
    assert r.status_code == 200
    assert "quiet day" in r.json()["narrative_md"].lower() or "quiet" in r.json()["narrative_md"].lower()


def test_weekly_generate_and_read(client):
    c, _ = client
    r = c.post("/api/insights/weekly/generate", json={"week": DATE})
    assert r.status_code == 200
    assert r.json()["insight_md"] == "Steady week."
    r = c.get("/api/insights/weekly", params={"week": DATE})
    assert r.json()["exists"] is True
    assert r.json()["wins"] == ["consistency"]
