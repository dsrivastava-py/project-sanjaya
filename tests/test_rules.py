"""Rule engine tests (PRD §8.4): seed coverage, specificity, subdomains,
priority (learned beats seed), and no-match."""
from __future__ import annotations

from sanjaya.db import now_ts
from sanjaya.rules.engine import RulesEngine


def _cat_id(db, name):
    return db.execute("SELECT id FROM categories WHERE name=?", (name,)).fetchone()["id"]


def test_github_domain_to_building_code(db):
    eng = RulesEngine(db)
    m = eng.classify(domain="github.com", exe="chrome.exe", title="x")
    assert m is not None
    assert m.kind_hint == "code"
    assert m.category_id == _cat_id(db, "Building (own products)")


def test_youtube_kind_only_no_category(db):
    eng = RulesEngine(db)
    m = eng.classify(domain="youtube.com")
    assert m.kind_hint == "youtube" and m.category_id is None


def test_ai_host_kind_only(db):
    eng = RulesEngine(db)
    assert eng.classify(domain="claude.ai").kind_hint == "ai_chat"


def test_placements_domain(db):
    eng = RulesEngine(db)
    assert eng.classify(domain="linkedin.com").category_id == _cat_id(db, "Placements")


def test_code_exe(db):
    eng = RulesEngine(db)
    m = eng.classify(exe="Code.exe")
    assert m.kind_hint == "code" and m.category_id == _cat_id(db, "Building (own products)")


def test_office_exe_doc_no_category(db):
    eng = RulesEngine(db)
    m = eng.classify(exe="WINWORD.EXE")
    assert m.kind_hint == "doc" and m.category_id is None


def test_media_exe_entertainment(db):
    eng = RulesEngine(db)
    m = eng.classify(exe="vlc.exe")
    assert m.kind_hint == "media" and m.category_id == _cat_id(db, "Entertainment")


def test_title_regex_placements(db):
    eng = RulesEngine(db)
    m = eng.classify(exe="notepad.exe", title="Placement prep sheet")
    assert m.category_id == _cat_id(db, "Placements")


def test_title_regex_agency(db):
    eng = RulesEngine(db)
    m = eng.classify(exe="notepad.exe", title="DevsCrest client invoice")
    assert m.category_id == _cat_id(db, "Agency (DevsCrest)")


def test_subdomain_matches(db):
    eng = RulesEngine(db)
    assert eng.classify(domain="www.github.com") is not None


def test_specificity_mail_google_is_social(db):
    eng = RulesEngine(db)
    m = eng.classify(domain="mail.google.com")
    assert m.category_id == _cat_id(db, "Social & Comms")


def test_no_match_returns_none(db):
    eng = RulesEngine(db)
    assert eng.classify(exe="unknown.exe", domain=None, title="random window") is None


def test_learned_rule_beats_seed(db):
    # learned rule (priority 50) overrides the github->Building seed
    college = _cat_id(db, "College")
    db.execute(
        "INSERT INTO rules(priority,matcher,pattern,kind_hint,category_id,source,created_ts)"
        " VALUES(50,'domain','github.com',NULL,?,'learned',?)",
        (college, now_ts()),
    )
    eng = RulesEngine(db)
    assert eng.classify(domain="github.com").category_id == college


def test_record_hit_increments(db):
    eng = RulesEngine(db)
    m = eng.classify(domain="github.com")
    before = db.execute("SELECT hit_count FROM rules WHERE id=?", (m.rule_id,)).fetchone()["hit_count"]
    eng.record_hit(m.rule_id)
    after = db.execute("SELECT hit_count FROM rules WHERE id=?", (m.rule_id,)).fetchone()["hit_count"]
    assert after == before + 1
