"""HTTP tests for the Phase 7 editing surface: PATCH/POST/DELETE /api/spans,
split, learned rules ("always classify like this"), review queue + bulk assign,
projects, and the edits_audit guarantee. Temp DB, no network.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from sanjaya import config as configmod, db as dbmod, paths
from sanjaya.rules.engine import RulesEngine
from sanjaya.runtime import RuntimeState
from sanjaya.server.app import create_app
from sanjaya.timeutil import day_bounds

DATE = "2026-07-10"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "DB_PATH", tmp_path / "api.db")
    dbmod.init_db()
    cfg = configmod.load(create=False)
    rt = RuntimeState()
    app = create_app(cfg, rt, controller=None)
    return TestClient(app), cfg, rt


def _cat_id(name: str) -> int:
    conn = dbmod.connect()
    cid = conn.execute("SELECT id FROM categories WHERE name=?", (name,)).fetchone()["id"]
    conn.close()
    return cid


def _mk_span(cfg, hour: float, minutes: int = 60, *, kind="app", cat=None,
             classified_by=None, ai_confidence=None, domain=None, url=None,
             exe=None, title=None) -> int:
    conn = dbmod.connect()
    lo = day_bounds(DATE, cfg.timezone, cfg.day_start_hour)[0] + int(hour * 3600)
    sid = dbmod.insert_span(conn, {
        "start_ts": lo, "end_ts": lo + minutes * 60, "kind": kind, "exe": exe,
        "app_name": None, "window_title": title, "url": url, "domain": domain,
        "detail": None, "category_id": cat, "project_id": None,
        "classified_by": classified_by, "rule_id": None,
        "ai_confidence": ai_confidence, "edited": 0,
    })
    conn.close()
    return sid


def _audit_count(entity: str, field: str | None = None) -> int:
    conn = dbmod.connect()
    q = "SELECT COUNT(*) c FROM edits_audit WHERE entity=?"
    args: list = [entity]
    if field:
        q += " AND field=?"
        args.append(field)
    n = conn.execute(q, args).fetchone()["c"]
    conn.close()
    return n


# --- PATCH /spans/{id} ---------------------------------------------------------
def test_patch_span_category_updates_totals_and_audits(client):
    c, cfg, _ = client
    plc = _cat_id("Placements")
    sid = _mk_span(cfg, 2, 60, cat=None)
    before = c.get(f"/api/day/{DATE}").json()
    assert before["category_totals"].get(str(plc), 0) == 0

    r = c.patch(f"/api/spans/{sid}", json={"category_id": plc})
    assert r.status_code == 200
    s = r.json()["span"]
    assert s["category_id"] == plc
    assert s["classified_by"] == "user"
    assert s["edited"] == 1

    after = c.get(f"/api/day/{DATE}").json()      # survives reload (recomputed from DB)
    assert after["category_totals"][str(plc)] == 3600
    assert _audit_count("span", "category_id") == 1


def test_patch_span_label_lands_in_detail(client):
    c, cfg, _ = client
    sid = _mk_span(cfg, 3, 30)
    r = c.patch(f"/api/spans/{sid}", json={"label": "DSA sheet"})
    assert r.status_code == 200
    assert json.loads(r.json()["span"]["detail"])["label"] == "DSA sheet"
    assert _audit_count("span", "label") == 1


def test_patch_idle_span_category_rejected(client):
    c, cfg, _ = client
    sid = _mk_span(cfg, 4, 30, kind="idle")
    r = c.patch(f"/api/spans/{sid}", json={"category_id": _cat_id("Placements")})
    assert r.status_code == 422


def test_patch_span_project_must_match_category(client):
    c, cfg, _ = client
    agency, plc = _cat_id("Agency (DevsCrest)"), _cat_id("Placements")
    pid = c.post("/api/projects", json={"name": "LAWFIRM", "category_id": agency}).json()["project"]["id"]
    sid = _mk_span(cfg, 5, 30)
    r = c.patch(f"/api/spans/{sid}", json={"category_id": plc, "project_id": pid})
    assert r.status_code == 422
    r = c.patch(f"/api/spans/{sid}", json={"category_id": agency, "project_id": pid})
    assert r.status_code == 200
    assert r.json()["span"]["project_id"] == pid


# --- learned rules ---------------------------------------------------------------
def test_learn_rule_retro_applies_and_classifies_next(client):
    c, cfg, rt = client
    plc = _cat_id("Placements")
    edited = _mk_span(cfg, 2, 30, domain="notion.so", cat=None)
    virgin = _mk_span(cfg, 6, 30, domain="notion.so", cat=None)               # unclassified
    ai_kept = _mk_span(cfg, 8, 30, domain="notion.so",
                       cat=_cat_id("Entertainment"), classified_by="ai", ai_confidence=0.9)

    r = c.patch(f"/api/spans/{edited}", json={"category_id": plc, "learn_rule": True})
    assert r.status_code == 200
    rule = r.json()["rule"]
    assert rule["matcher"] == "domain" and rule["pattern"] == "notion.so"
    assert rule["retro_applied"] == 1                     # only the virgin span

    conn = dbmod.connect()
    row = conn.execute("SELECT * FROM rules WHERE id=?", (rule["rule_id"],)).fetchone()
    assert (row["priority"], row["source"]) == (50, "learned")
    v = conn.execute("SELECT category_id, classified_by FROM spans WHERE id=?", (virgin,)).fetchone()
    assert (v["category_id"], v["classified_by"]) == (plc, "rule")
    a = conn.execute("SELECT category_id FROM spans WHERE id=?", (ai_kept,)).fetchone()
    assert a["category_id"] == _cat_id("Entertainment")   # AI verdict never overridden

    # the collector reload signal fired, and a freshly loaded engine
    # classifies the next matching span with the learned rule
    assert rt.rules_version == 1
    eng = RulesEngine(conn)
    m = eng.classify(domain="notion.so")
    assert m is not None and m.category_id == plc and m.rule_id == rule["rule_id"]
    conn.close()


def test_learn_rule_prefers_url_prefix(client):
    c, cfg, _ = client
    plc = _cat_id("Placements")
    sid = _mk_span(cfg, 2, 30, domain="leetcode.com",
                   url="https://leetcode.com/problems/two-sum/?envType=daily")
    r = c.patch(f"/api/spans/{sid}", json={"category_id": plc, "learn_rule": True})
    rule = r.json()["rule"]
    assert rule["matcher"] == "url_prefix"
    assert rule["pattern"] == "https://leetcode.com/problems/two-sum/"   # query stripped


# --- manual spans -----------------------------------------------------------------
def test_manual_span_add_and_idle_retag(client):
    c, cfg, _ = client
    plc = _cat_id("Placements")
    lo = day_bounds(DATE, cfg.timezone, cfg.day_start_hour)[0]
    _mk_span(cfg, 10, 120, kind="idle")                    # 10:00–12:00 idle (2h)

    r = c.post("/api/spans", json={"start_ts": lo + 10 * 3600, "end_ts": lo + 11 * 3600,
                                   "category_id": plc, "label": "Gym"})
    assert r.status_code == 200
    s = r.json()["span"]
    assert s["kind"] == "manual" and s["classified_by"] == "user"

    d = c.get(f"/api/day/{DATE}").json()
    assert d["category_totals"][str(plc)] == 3600          # manual counts as tracked
    assert d["idle_seconds"] == 3600                       # overlap re-tagged, not doubled
    assert d["goals"] == []                                # no goals yet — shape intact
    assert _audit_count("span", "create") == 1


def test_manual_span_validation(client):
    c, cfg, _ = client
    lo = day_bounds(DATE, cfg.timezone, cfg.day_start_hour)[0]
    assert c.post("/api/spans", json={"start_ts": lo, "end_ts": lo}).status_code == 422
    assert c.post("/api/spans", json={"start_ts": lo}).status_code == 422
    assert c.post("/api/spans", json={"start_ts": lo, "end_ts": lo + 90000}).status_code == 422


# --- split / delete -----------------------------------------------------------------
def test_split_span(client):
    c, cfg, _ = client
    plc = _cat_id("Placements")
    sid = _mk_span(cfg, 2, 60, cat=plc)
    conn = dbmod.connect()
    start = conn.execute("SELECT start_ts FROM spans WHERE id=?", (sid,)).fetchone()["start_ts"]
    conn.close()

    r = c.post(f"/api/spans/{sid}/split", json={"at_ts": start + 1200})
    assert r.status_code == 200
    head, tail = r.json()["spans"]
    assert head["end_ts"] == tail["start_ts"] == start + 1200
    assert head["edited"] == 1 and tail["edited"] == 1
    assert (head["end_ts"] - head["start_ts"]) + (tail["end_ts"] - tail["start_ts"]) == 3600
    assert tail["category_id"] == plc                      # tail inherits everything
    assert _audit_count("span", "split") == 1

    # out-of-range split point rejected
    assert c.post(f"/api/spans/{sid}/split", json={"at_ts": start}).status_code == 422


def test_delete_span(client):
    c, cfg, _ = client
    sid = _mk_span(cfg, 2, 60, cat=_cat_id("Placements"))
    assert c.delete(f"/api/spans/{sid}").status_code == 200
    assert c.get(f"/api/day/{DATE}").json()["spans"] == []
    assert _audit_count("span", "delete") == 1
    assert c.delete(f"/api/spans/{sid}").status_code == 404


# --- review queue ---------------------------------------------------------------------
def test_review_queue_groups_and_bulk_assign(client):
    c, cfg, rt = client
    plc = _cat_id("Placements")
    a = _mk_span(cfg, 2, 30, domain="notion.so", title="Roadmap – Notion")
    b = _mk_span(cfg, 3, 40, domain="notion.so", title="Notes – Notion")
    low = _mk_span(cfg, 5, 20, domain="medium.com",
                   cat=_cat_id("Personal Growth"), classified_by="ai", ai_confidence=0.5)
    _mk_span(cfg, 7, 60, domain="github.com", cat=_cat_id("Building (own products)"),
             classified_by="rule")                          # classified: not in queue
    _mk_span(cfg, 9, 60, kind="idle")                       # idle: never in queue

    q = c.get("/api/review").json()
    keys = {g["key"]: g for g in q["groups"]}
    assert set(keys) == {"notion.so", "medium.com"}
    assert keys["notion.so"]["count"] == 2
    assert keys["notion.so"]["total_s"] == 70 * 60
    assert sorted(keys["notion.so"]["span_ids"]) == sorted([a, b])

    r = c.post("/api/review/assign",
               json={"span_ids": [a, b, low], "category_id": plc, "learn_rule": True})
    assert r.status_code == 200
    assert r.json()["updated"] == 3
    # one learned rule per distinct identity in the batch, not just the first
    learned = {(ru["matcher"], ru["pattern"]) for ru in r.json()["rules"]}
    assert learned == {("domain", "notion.so"), ("domain", "medium.com")}
    assert rt.rules_version == 2
    assert c.get("/api/review").json()["groups"] == []      # queue drained
    conn = dbmod.connect()
    rows = conn.execute("SELECT classified_by, edited, category_id FROM spans WHERE id IN (?,?,?)",
                        (a, b, low)).fetchall()
    conn.close()
    assert all(r["classified_by"] == "user" and r["edited"] == 1 and r["category_id"] == plc
               for r in rows)
    assert _audit_count("span", "category_id") == 3


def test_review_assign_validation(client):
    c, _, _ = client
    assert c.post("/api/review/assign", json={"span_ids": [], "category_id": 1}).status_code == 422
    assert c.post("/api/review/assign", json={"span_ids": [1]}).status_code == 422


# --- projects -----------------------------------------------------------------------
def test_projects_create_list_and_duplicate(client):
    c, _, _ = client
    agency = _cat_id("Agency (DevsCrest)")
    r = c.post("/api/projects", json={"name": "Crest Billings", "category_id": agency})
    assert r.status_code == 200
    assert r.json()["project"]["name"] == "Crest Billings"
    assert c.post("/api/projects", json={"name": "Crest Billings", "category_id": agency}).status_code == 409
    assert c.post("/api/projects", json={"name": "", "category_id": agency}).status_code == 422
    assert c.post("/api/projects", json={"name": "X"}).status_code == 422
    names = [p["name"] for p in c.get("/api/projects").json()["projects"]]
    assert "Crest Billings" in names
