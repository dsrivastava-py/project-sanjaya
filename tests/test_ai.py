"""AI-layer tests (PRD §9, Phase 4). A fake client stands in for Groq — the live
endpoint is NEVER hit (§15). Covers: batch classification + confidence floor,
queue persistence across a network failure, redaction, and the token budget.
"""
from __future__ import annotations

import json
import re

import pytest

from sanjaya import config as configmod, db as dbmod, paths
from sanjaya.ai import budget, jobs, prompts
from sanjaya.ai import redact


# --- fakes -------------------------------------------------------------------
class FakeClient:
    """Implements the GroqClient.complete contract without any network."""

    def __init__(self, classifications=None, raise_exc=None, tokens=1234):
        self._cls = classifications
        self._raise = raise_exc
        self.tokens = tokens
        self.calls: list[dict] = []

    def complete(self, conn, *, kind, model, system, user, json_mode=True, temperature=0.2):
        self.calls.append({"kind": kind, "model": model, "system": system, "user": user})
        if self._raise is not None:
            raise self._raise
        return {"data": {"classifications": self._cls or []},
                "text": "", "total_tokens": self.tokens}


@pytest.fixture()
def cfg():
    return configmod.load(create=False)


def _add_unknown(conn, i, *, kind="web", domain=None, title="", app="Google Chrome",
                 url=None, detail=None):
    span = {
        "start_ts": 1000 + i * 60, "end_ts": 1000 + i * 60 + 30, "kind": kind,
        "exe": "chrome.exe", "app_name": app, "window_title": title,
        "url": url, "domain": domain, "detail": detail,
        "category_id": None, "project_id": None, "classified_by": None,
        "rule_id": None, "ai_confidence": None, "edited": 0,
    }
    sid = dbmod.insert_span(conn, span)
    conn.execute("INSERT INTO ai_queue(kind,payload,created_ts) VALUES('classify',?,?)",
                 (json.dumps({"span_id": sid}), 1000))
    return sid


def _cat_id(conn, name):
    return conn.execute("SELECT id FROM categories WHERE name=?", (name,)).fetchone()["id"]


# --- classify batch + confidence floor --------------------------------------
def test_classify_applies_above_floor_only(db, cfg):
    ids = [_add_unknown(db, i, domain=f"site{i}.com", title=f"page {i}") for i in range(6)]
    cls = [
        {"i": 0, "category": "Placements", "project": None, "confidence": 0.9},
        {"i": 1, "category": "Entertainment", "project": None, "confidence": 0.4},  # below floor
        {"i": 2, "category": "NoSuchCategory", "project": None, "confidence": 0.95}, # unknown cat
        {"i": 3, "category": "Agency (DevsCrest)", "project": None, "confidence": 0.7},
        {"i": 4, "category": "College", "project": None, "confidence": 0.6},         # exactly floor
        {"i": 5, "category": "Social & Comms", "project": None, "confidence": 0.99},
    ]
    res = jobs.run_classify_batch(db, FakeClient(cls), cfg)
    assert res["classified"] == 4

    def cat_of(sid):
        return db.execute("SELECT category_id, classified_by, ai_confidence FROM spans WHERE id=?",
                          (sid,)).fetchone()

    assert cat_of(ids[0])["category_id"] == _cat_id(db, "Placements")
    assert cat_of(ids[0])["classified_by"] == "ai"
    assert cat_of(ids[1])["category_id"] is None      # below floor -> Review
    assert cat_of(ids[2])["category_id"] is None      # unknown category ignored
    assert cat_of(ids[4])["category_id"] == _cat_id(db, "College")
    # queue drained
    pending = db.execute("SELECT COUNT(*) c FROM ai_queue WHERE status='pending'").fetchone()["c"]
    assert pending == 0


def test_classify_twenty_ambiguous_spans(db, cfg):
    for i in range(20):
        _add_unknown(db, i, domain=f"amb{i}.com", title=f"thing {i}")
    cls = [{"i": i, "category": "Personal Growth", "project": None, "confidence": 0.8}
           for i in range(20)]
    res = jobs.run_classify_batch(db, FakeClient(cls), cfg)
    assert res["picked"] == 20 and res["classified"] == 20
    remaining = db.execute(
        "SELECT COUNT(*) c FROM spans WHERE category_id IS NULL AND kind NOT IN "
        "('idle','locked','manual')").fetchone()["c"]
    assert remaining == 0


def test_classify_never_overrides_existing(db, cfg):
    sid = _add_unknown(db, 0, domain="x.com", title="x")
    db.execute("UPDATE spans SET category_id=?, classified_by='user' WHERE id=?",
               (_cat_id(db, "Placements"), sid))
    cls = [{"i": 0, "category": "Entertainment", "project": None, "confidence": 0.99}]
    jobs.run_classify_batch(db, FakeClient(cls), cfg)
    row = db.execute("SELECT category_id, classified_by FROM spans WHERE id=?", (sid,)).fetchone()
    assert row["classified_by"] == "user"
    assert row["category_id"] == _cat_id(db, "Placements")


# --- queue persistence across a network failure ------------------------------
def test_queue_persists_on_network_failure_then_drains(db, cfg):
    ids = [_add_unknown(db, i, domain=f"n{i}.com", title=f"n {i}") for i in range(3)]

    with pytest.raises(Exception):
        jobs.run_classify_batch(db, FakeClient(raise_exc=RuntimeError("net down")), cfg)

    rows = db.execute("SELECT status, attempts, last_error FROM ai_queue").fetchall()
    assert all(r["status"] == "pending" for r in rows)     # requeued, not lost
    assert all(r["attempts"] == 1 for r in rows)
    assert all("net down" in (r["last_error"] or "") for r in rows)
    # spans still uncategorized
    assert db.execute("SELECT COUNT(*) c FROM spans WHERE category_id IS NULL").fetchone()["c"] == 3

    # reconnect: drains cleanly
    cls = [{"i": i, "category": "College", "project": None, "confidence": 0.9} for i in range(3)]
    res = jobs.run_classify_batch(db, FakeClient(cls), cfg)
    assert res["classified"] == 3
    assert db.execute("SELECT COUNT(*) c FROM ai_queue WHERE status='done'").fetchone()["c"] == 3


# --- redaction (§9.2) --------------------------------------------------------
def test_redact_text_applies_user_patterns():
    compiled = redact.compile_patterns([r"\d{3}-\d{4}", r"(?i)secret\w+"])
    assert redact.redact_text("call 555-1234 about SecretProject", compiled) == \
        "call [redacted] about [redacted]"


def test_records_carry_domain_not_full_url(db):
    # build a record straight from a span with a revealing URL
    span = {"app_name": "Google Chrome", "kind": "youtube",
            "window_title": "Cool Video", "domain": "youtube.com",
            "url": "https://youtube.com/watch?v=SECRET123&t=42",
            "detail": json.dumps({"video_title": "Cool Video", "channel": "Chan"})}
    rec = jobs._build_records([span])[0]
    assert rec["domain"] == "youtube.com"
    assert "url" not in rec                       # full URL never leaves (§9.2)
    _, user = prompts.classifier(["College"], {}, [rec])
    assert "SECRET123" not in user
    assert "watch?v=" not in user
    assert "youtube.com" in user


def test_debug_dump_writes_redacted_only(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "AI_PAYLOAD_DIR", tmp_path)
    compiled = redact.compile_patterns([r"TOKEN\w+"])
    system = redact.redact_text("system TOKENabc123", compiled)
    user = redact.redact_text("user data clean", compiled)
    redact.dump_payload("classify", 1700000000, system, user)
    written = (tmp_path / "1700000000_classify.json").read_text(encoding="utf-8")
    assert "TOKENabc123" not in written
    assert "[redacted]" in written


# --- budget (§9.4) -----------------------------------------------------------
def test_budget_counts_and_caps(db):
    low = configmod.Config({"general": {"timezone": "Asia/Kolkata", "day_start_hour": 4},
                            "ai": {"ai_daily_token_cap": 50}})
    assert budget.tokens_today(db, low) == 0
    budget.add_tokens(db, low, 30)
    assert budget.tokens_today(db, low) == 30
    assert budget.over_cap(db, low) is False
    budget.add_tokens(db, low, 40)                 # now 70 >= cap 50
    assert budget.over_cap(db, low) is True
    assert dbmod.get_setting(db, "ai_budget_paused") == "1"


def test_classify_paused_when_over_cap(db):
    low = configmod.Config({"general": {"timezone": "Asia/Kolkata", "day_start_hour": 4},
                            "ai": {"ai_daily_token_cap": 10,
                                   "classify_model": "llama-3.1-8b-instant"}})
    budget.add_tokens(db, low, 100)
    _add_unknown(db, 0, domain="x.com", title="x")
    fake = FakeClient([{"i": 0, "category": "College", "confidence": 0.9}])
    res = jobs.run_classify_batch(db, fake, low)
    assert res.get("paused") is True
    assert fake.calls == []                          # never called the model
