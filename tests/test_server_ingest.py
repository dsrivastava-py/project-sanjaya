"""Server, ingest, and reconciliation tests (PRD §8.8, §10.7, Phase 3).

Uses FastAPI's TestClient — never binds a real socket and never touches the
live Groq endpoint. The ingest token is injected via the environment.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from sanjaya import config as configmod, db as dbmod
from sanjaya.collector.spans import SpanBuilder
from sanjaya.rules.engine import RulesEngine
from sanjaya.runtime import ExtEvent, RuntimeState
from sanjaya.server.app import create_app

TOKEN = "test-token-abc123"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("SANJAYA_INGEST_TOKEN", TOKEN)
    dbmod.init_db()  # /status needs a real DB
    cfg = configmod.load(create=False)
    state = RuntimeState()
    app = create_app(cfg, state, controller=None)
    return TestClient(app)


# --- /status -----------------------------------------------------------------
def test_status_shape(client):
    r = client.get("/api/status")
    assert r.status_code == 200
    d = r.json()
    assert d["version"]
    assert set(d["collector"]) >= {"alive", "last_tick_ts", "paused"}
    assert "last_seen_ts" in d["extension"]
    assert set(d["ai_queue"]) == {"pending", "failed"}


def test_status_reports_no_collector_before_any_tick(client):
    d = client.get("/api/status").json()
    assert d["collector"]["alive"] is False
    assert d["extension"]["last_seen_ts"] is None


# --- /ingest/browser token auth ---------------------------------------------
def test_ingest_missing_token_401(client):
    r = client.post("/ingest/browser", json={"url": "https://x.com/", "title": "X"})
    assert r.status_code == 401


def test_ingest_bad_token_401(client):
    r = client.post("/ingest/browser", json={"url": "https://x.com/"},
                    headers={"X-Sanjaya-Token": "wrong"})
    assert r.status_code == 401


# --- /ingest/browser records events -----------------------------------------
def test_ingest_single_event_records_last_seen(client):
    r = client.post(
        "/ingest/browser",
        json={"ts": 1700000000, "url": "https://www.google.com/search?q=fastapi+cors",
              "title": "fastapi cors - Google Search", "favicon_domain": "google.com"},
        headers={"X-Sanjaya-Token": TOKEN},
    )
    assert r.status_code == 200
    assert r.json()["accepted"] == 1
    # /status now reports the extension as seen
    d = client.get("/api/status").json()
    assert d["extension"]["last_seen_ts"] == 1700000000


def test_ingest_youtube_event_carries_detail(client):
    body = {
        "ts": 1700000100,
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "title": "Never Gonna Give You Up",
        "favicon_domain": "youtube.com",
        "audible": True,
        "youtube": {"video_id": "dQw4w9WgXcQ", "title": "Never Gonna Give You Up",
                    "channel": "Rick Astley", "playing": True, "position": 42},
    }
    r = client.post("/ingest/browser", json=body, headers={"X-Sanjaya-Token": TOKEN})
    assert r.json() == {"accepted": 1, "last_seen_ts": 1700000100}


def test_ingest_batch(client):
    body = {"events": [
        {"ts": 1700000200, "url": "https://a.com/", "title": "A"},
        {"ts": 1700000201, "url": "https://b.com/", "title": "B"},
    ]}
    r = client.post("/ingest/browser", json=body, headers={"X-Sanjaya-Token": TOKEN})
    assert r.json()["accepted"] == 2
    assert r.json()["last_seen_ts"] == 1700000201


# --- reconciliation window (±3s) --------------------------------------------
def test_runtime_reconcile_window():
    st = RuntimeState()
    st.record_ext_event(ExtEvent(ts=1000, url="https://x.com/", domain="x.com"))
    assert st.latest_ext_within(1003, 3) is not None   # within window
    assert st.latest_ext_within(997, 3) is not None    # symmetric
    assert st.latest_ext_within(1004, 3) is None        # just outside
    assert st.last_ext_ts == 1000


def test_reconciliation_upgrades_youtube_span(db):
    """An extension YouTube event upgrades a chrome foreground span: kind youtube,
    url/domain/channel attached (PRD §8.8)."""
    st = RuntimeState()
    st.record_ext_event(ExtEvent(
        ts=1000, url="https://www.youtube.com/watch?v=abc123",
        title="Cool Video", domain="youtube.com",
        detail={"video_id": "abc123", "video_title": "Cool Video",
                "channel": "Cool Channel", "playing": True},
    ))
    engine = RulesEngine(db)
    b = SpanBuilder(db, engine)

    ts = 1001
    ev = st.latest_ext_within(ts, 3)
    assert ev is not None
    # this mirrors exactly what the collector loop does when chrome is foreground
    b.on_active(ts, "chrome.exe", "Google Chrome", ev.title,
                url=ev.url, domain=ev.domain, ext_detail=ev.detail)
    b.shutdown(ts + 10)

    row = db.execute(
        "SELECT kind,url,domain,detail,classified_by FROM spans ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert row["kind"] == "youtube"            # seed rule kind_hint
    assert "abc123" in row["url"]
    assert row["domain"].endswith("youtube.com")
    detail = json.loads(row["detail"])
    assert detail["channel"] == "Cool Channel"
    assert detail["video_id"] == "abc123"


def test_reconciliation_fallback_without_extension(db):
    """Extension silent -> title parsing still yields a youtube span (§8.8)."""
    engine = RulesEngine(db)
    b = SpanBuilder(db, engine)
    b.on_active(1000, "chrome.exe", "Google Chrome", "Cool Video - YouTube")
    b.shutdown(1010)
    row = db.execute("SELECT kind,detail FROM spans ORDER BY id DESC LIMIT 1").fetchone()
    assert row["kind"] == "youtube"
    assert json.loads(row["detail"])["video_title"] == "Cool Video"
