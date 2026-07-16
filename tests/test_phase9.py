"""Phase 9 acceptance tests (PRD §14): settings/privacy/export/polish.

Covers: exclude list enforcement (DB + AI payload path), redaction settings via
the API, export round-trip (JSON/CSV/Markdown), rules + category/project
managers, retention trim, and stopwatch parsing/transitions.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from sanjaya import config as configmod, db as dbmod, export as exportmod, privacy
from sanjaya.collector.spans import SpanBuilder
from sanjaya.collector.stopwatch import StopwatchReader, parse_time_to_seconds
from sanjaya.rules.engine import RulesEngine
from sanjaya.runtime import RuntimeState
from sanjaya.server.app import create_app
from sanjaya.server.scheduler import retention_trim


@pytest.fixture()
def cfg():
    return configmod.load(create=False)


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """TestClient over a fresh temp DB (dbmod.connect patched to it)."""
    path = tmp_path / "api.db"
    real_connect = dbmod.connect

    def connect(p=None):
        return real_connect(path if p is None else p)

    monkeypatch.setattr(dbmod, "connect", connect)
    dbmod.init_db(path)
    cfg = configmod.load(create=False)
    app = create_app(cfg, RuntimeState(), controller=None)
    return TestClient(app)


def _cat_id(conn, name):
    return conn.execute("SELECT id FROM categories WHERE name=?", (name,)).fetchone()["id"]


# --- exclude list enforcement (§13.10; acceptance: excluded exe/domain never
# --- appears in the DB with a real title nor in an AI payload) -----------------
def test_excluded_exe_span_scrubbed_before_persist(db):
    dbmod.set_setting(db, "exclude_exes", json.dumps(["1password.exe"]))
    engine = RulesEngine(db)
    b = SpanBuilder(db, engine)
    b.on_active(1000, "1Password.exe", "1Password", "Vault — my bank logins")
    b.shutdown(1010)
    row = db.execute("SELECT kind, window_title, url, detail, category_id FROM spans "
                     "ORDER BY id DESC LIMIT 1").fetchone()
    assert row["window_title"] == privacy.EXCLUDED_TITLE
    assert row["kind"] == "app"
    assert row["url"] is None and row["detail"] is None
    assert row["category_id"] is None


def test_excluded_domain_never_reaches_ai_queue(db):
    dbmod.set_setting(db, "exclude_domains", json.dumps(["mybank.com"]))
    engine = RulesEngine(db)
    queued: list[dict] = []
    b = SpanBuilder(db, engine, enqueue_unknown=queued.append)
    b.on_active(1000, "chrome.exe", "Google Chrome", "Accounts - My Bank",
                url="https://secure.mybank.com/accounts", domain="secure.mybank.com")
    b.shutdown(1010)
    assert queued == []                                  # never classified by AI
    row = db.execute("SELECT window_title, url FROM spans ORDER BY id DESC LIMIT 1").fetchone()
    assert row["window_title"] == privacy.EXCLUDED_TITLE
    assert row["url"] is None


def test_non_excluded_span_untouched(db):
    dbmod.set_setting(db, "exclude_exes", json.dumps(["1password.exe"]))
    engine = RulesEngine(db)
    b = SpanBuilder(db, engine)
    b.on_active(1000, "Code.exe", "Visual Studio Code", "api.py — sanjaya — Visual Studio Code")
    b.shutdown(1010)
    row = db.execute("SELECT window_title, classified_by FROM spans ORDER BY id DESC LIMIT 1").fetchone()
    assert "api.py" in row["window_title"]
    assert row["classified_by"] == "rule"                # Code.exe seed rule


def test_wildcard_exe_and_subdomain_matching(db):
    dbmod.set_setting(db, "exclude_exes", json.dumps(["keepass*.exe"]))
    dbmod.set_setting(db, "exclude_domains", json.dumps(["bank.co"]))
    assert privacy.is_excluded(db, exe="KeePassXC.exe")
    assert privacy.is_excluded(db, domain="online.bank.co")
    assert not privacy.is_excluded(db, exe="notepad.exe", domain="github.com")
    # substring is NOT a match: 'mybank.co.evil.com' must not hit 'bank.co'
    assert not privacy.is_excluded(db, domain="notbank.com")


# --- settings API (§10.6) ------------------------------------------------------
def test_settings_roundtrip(client):
    r = client.get("/api/settings")
    assert r.status_code == 200
    s = r.json()["settings"]
    assert "exclude_exes" in s and "redaction_patterns" in s
    assert s["retention_months"] == 0

    r = client.patch("/api/settings", json={
        "exclude_domains": ["mybank.com"],
        "redaction_patterns": [r"\d{12}"],
        "retention_months": 6,
        "debug_ai_payloads": True,
        "summary_time": "22:00",
    })
    assert r.status_code == 200
    s = r.json()["settings"]
    assert s["exclude_domains"] == ["mybank.com"]
    assert s["retention_months"] == 6
    assert s["debug_ai_payloads"] is True
    assert s["summary_time"] == "22:00"
    # persists across requests
    s2 = client.get("/api/settings").json()["settings"]
    assert s2 == s


def test_settings_rejects_bad_values(client):
    assert client.patch("/api/settings", json={"exclude_exes": "not-a-list"}).status_code == 422
    assert client.patch("/api/settings", json={"retention_months": -1}).status_code == 422
    assert client.patch("/api/settings", json={"nonsense_key": 1}).status_code == 422


# --- rules manager (§10.6) -----------------------------------------------------
def test_rules_crud_and_audit(client):
    r = client.get("/api/rules")
    n_seed = len(r.json()["rules"])
    assert n_seed >= 25

    r = client.post("/api/rules", json={"matcher": "domain", "pattern": "figma.com",
                                        "category_id": 1, "priority": 60})
    assert r.status_code == 200
    rid = r.json()["rule"]["id"]
    assert r.json()["rule"]["source"] == "user"

    r = client.patch(f"/api/rules/{rid}", json={"pattern": "www.figma.com"})
    assert r.json()["rule"]["pattern"] == "www.figma.com"

    r = client.delete(f"/api/rules/{rid}")
    assert r.json()["deleted"] is True
    assert len(client.get("/api/rules").json()["rules"]) == n_seed

    assert client.post("/api/rules", json={"matcher": "bogus", "pattern": "x"}).status_code == 422


# --- category / project managers (§10.6) ----------------------------------------
def test_category_manager(client):
    r = client.post("/api/categories", json={"name": "Health", "color_slot": None,
                                             "is_productive": True})
    cid = r.json()["category"]["id"]
    r = client.patch(f"/api/categories/{cid}", json={"name": "Health & Fitness",
                                                     "is_productive": False, "archived": True})
    c = r.json()["category"]
    assert c["name"] == "Health & Fitness" and c["is_productive"] == 0 and c["archived"] == 1
    assert client.post("/api/categories", json={"name": "College"}).status_code == 409
    assert client.patch(f"/api/categories/{cid}", json={"color_slot": 9}).status_code == 422


def test_project_manager(client):
    r = client.post("/api/projects", json={"name": "LawFirm site", "category_id": 1})
    pid = r.json()["project"]["id"]
    r = client.patch(f"/api/projects/{pid}", json={"name": "LawFirm v2"})
    assert r.json()["project"]["name"] == "LawFirm v2"
    r = client.delete(f"/api/projects/{pid}")
    assert r.json()["archived"] is True


# --- export (§10.6; acceptance: Markdown reads like a journal page, JSON
# --- round-trips) ---------------------------------------------------------------
def _seed_day(conn, cfg, date="2026-07-10"):
    from sanjaya.timeutil import day_bounds
    lo, _hi = day_bounds(date, cfg.timezone, cfg.day_start_hour)
    cat = _cat_id(conn, "Placements")
    dbmod.insert_span(conn, {
        "start_ts": lo + 3600, "end_ts": lo + 3600 + 5400, "kind": "web",
        "exe": "chrome.exe", "app_name": "Google Chrome",
        "window_title": "DSA sheet - LeetCode", "url": None, "domain": "leetcode.com",
        "detail": None, "category_id": cat, "project_id": None,
        "classified_by": "rule", "rule_id": None, "ai_confidence": None, "edited": 0,
    })
    conn.execute(
        "INSERT INTO day_summaries(date, narrative_md, highlights, focus_score, user_note_md) "
        "VALUES(?,?,?,?,?)",
        (date, "You spent the morning on LeetCode grinding DSA.",
         json.dumps(["Solved 5 DSA problems"]), 72.5, "Felt sharp today."),
    )
    return date, cat


def test_json_export_round_trips(db, cfg):
    date, cat = _seed_day(db, cfg)
    text = exportmod.json_export(db, cfg, date, date)
    data = json.loads(text)
    assert data["spans"][0]["category"] == "Placements"
    assert data["spans"][0]["duration_s"] == 5400
    assert data["summaries"][0]["date"] == date
    assert isinstance(data["goals"], list)


def test_csv_export_has_span_rows(db, cfg):
    date, _ = _seed_day(db, cfg)
    text = exportmod.csv_export(db, cfg, date, date)
    lines = text.strip().splitlines()
    assert lines[0].startswith("id,start_ts,end_ts,duration_s,kind")
    assert len(lines) == 2
    assert "Placements" in lines[1]


def test_markdown_export_reads_like_journal(db, cfg):
    date, _ = _seed_day(db, cfg)
    md = exportmod.markdown_export(db, cfg, date, date)
    assert f"## {date}" in md
    assert "You spent the morning on LeetCode" in md
    assert "- Solved 5 DSA problems" in md
    assert "**Placements:** 1h 30m" in md
    assert "Felt sharp today." in md


def test_export_endpoint_content_disposition(client):
    r = client.get("/api/export?format=md&from=2026-07-01&to=2026-07-02")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    assert r.headers["content-type"].startswith("text/markdown")
    assert client.get("/api/export?format=xml&from=2026-07-01&to=2026-07-02").status_code == 422


# --- retention trim (§7) ---------------------------------------------------------
def test_retention_trim_respects_summaries_and_zero(db, cfg):
    date, _ = _seed_day(db, cfg, "2020-01-10")     # ancient day WITH a summary
    # ancient day WITHOUT a summary must survive any trim
    dbmod.insert_span(db, {
        "start_ts": 1500000000, "end_ts": 1500000600, "kind": "app",
        "exe": "x.exe", "app_name": "X", "window_title": "old orphan",
        "url": None, "domain": None, "detail": None, "category_id": None,
        "project_id": None, "classified_by": None, "rule_id": None,
        "ai_confidence": None, "edited": 0,
    })
    assert retention_trim(db, cfg) == 0            # retention_months default 0 = keep forever
    dbmod.set_setting(db, "retention_months", 12)
    removed = retention_trim(db, cfg)
    assert removed == 1                            # only the summarized day's span
    assert db.execute("SELECT COUNT(*) c FROM spans").fetchone()["c"] == 1
    assert db.execute("SELECT COUNT(*) c FROM day_summaries").fetchone()["c"] == 1  # summary kept


# --- stopwatch (§8.7) -------------------------------------------------------------
def test_parse_time_to_seconds():
    assert parse_time_to_seconds("25:00 - pomofocus") == 1500
    assert parse_time_to_seconds("Timer 1:02:03 running") == 3723
    assert parse_time_to_seconds("00:07") == 7
    assert parse_time_to_seconds("no time here") is None
    assert parse_time_to_seconds("v1.2:34x") is None    # digit-flanked, not a reading


def test_web_timer_pause_and_close_transitions(db):
    sw = StopwatchReader(db)
    sw.available = False    # force the web-timer path only
    # ticking timer on pomofocus
    sw.read("chrome.exe", title="24:59 - pomofocus", domain="pomofocus.io", ts=1000)
    sw.read("chrome.exe", title="24:57 - pomofocus", domain="pomofocus.io", ts=1002)
    # value freezes -> paused recorded once
    sw.read("chrome.exe", title="24:57 - pomofocus", domain="pomofocus.io", ts=1008)
    sw.read("chrome.exe", title="24:57 - pomofocus", domain="pomofocus.io", ts=1012)
    # tab switched away -> closed recorded with last value
    sw.read("chrome.exe", title="GitHub", domain="github.com", ts=1014)
    rows = db.execute("SELECT source, last_value_s, event FROM stopwatch_readings ORDER BY id").fetchall()
    events = [(r["source"], r["last_value_s"], r["event"]) for r in rows]
    assert ("web:pomofocus.io", 24 * 60 + 57, "paused") in events
    assert ("web:pomofocus.io", 24 * 60 + 57, "closed") in events
    assert len([e for e in events if e[2] == "paused"]) == 1
