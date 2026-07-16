"""Phase 0 acceptance: empty DB is created with the full schema + seeds."""
from __future__ import annotations

from sanjaya import db as dbmod

EXPECTED_TABLES = {
    "meta", "categories", "projects", "spans", "rules", "stopwatch_readings",
    "day_summaries", "goals", "goal_progress", "ai_queue", "edits_audit",
    "settings",
}


def test_all_tables_created(db):
    rows = db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    names = {r["name"] for r in rows}
    assert EXPECTED_TABLES.issubset(names)


def test_schema_version_recorded(db):
    assert int(dbmod.get_meta(db, "schema_version")) == dbmod.SCHEMA_VERSION


def test_seed_categories(db):
    rows = db.execute("SELECT name, color_slot FROM categories ORDER BY sort").fetchall()
    names = [r["name"] for r in rows]
    assert names[0] == "Agency (DevsCrest)"
    assert len(names) == 8
    # color slots are the fixed 1..8 assignment from §4.3
    assert [r["color_slot"] for r in rows] == list(range(1, 9))


def test_seed_rules_present(db):
    n = db.execute("SELECT COUNT(*) c FROM rules").fetchone()["c"]
    assert n >= 25
    # YouTube rule sets kind but leaves category ambiguous (NULL)
    yt = db.execute(
        "SELECT kind_hint, category_id FROM rules WHERE pattern='youtube.com'"
    ).fetchone()
    assert yt["kind_hint"] == "youtube" and yt["category_id"] is None


def test_migrate_idempotent(tmp_path):
    path = tmp_path / "x.db"
    conn = dbmod.connect(path)
    dbmod.migrate(conn)
    dbmod.migrate(conn)  # second run must not duplicate seeds
    assert conn.execute("SELECT COUNT(*) c FROM categories").fetchone()["c"] == 8
    conn.close()


def test_generated_duration_column(db):
    db.execute(
        "INSERT INTO spans(start_ts,end_ts,kind) VALUES(100,160,'app')"
    )
    row = db.execute("SELECT duration_s FROM spans").fetchone()
    assert row["duration_s"] == 60
