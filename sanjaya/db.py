"""SQLite access layer: schema (PRD §7 DDL verbatim), migration runner, seed
data (§4.3 categories, §8.4 rules), and small DAL helpers used across the app.

One local file, WAL mode, transactional. No ORM — the schema is small and the
queries are hand-written for clarity and control.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from . import paths
from .timeutil import now_ts

# Bump when SCHEMA_SQL or the migration chain changes.
SCHEMA_VERSION = 1

# --- §7 data model -----------------------------------------------------------
SCHEMA_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE IF NOT EXISTS categories (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  color_slot INTEGER,
  is_productive INTEGER NOT NULL DEFAULT 1,
  sort INTEGER NOT NULL DEFAULT 0,
  archived INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS projects (
  id INTEGER PRIMARY KEY,
  category_id INTEGER NOT NULL REFERENCES categories(id),
  name TEXT NOT NULL,
  archived INTEGER NOT NULL DEFAULT 0,
  UNIQUE(category_id, name)
);

CREATE TABLE IF NOT EXISTS spans (
  id INTEGER PRIMARY KEY,
  start_ts INTEGER NOT NULL,
  end_ts   INTEGER NOT NULL,
  duration_s INTEGER GENERATED ALWAYS AS (end_ts - start_ts) STORED,
  kind TEXT NOT NULL CHECK (kind IN
    ('app','web','youtube','ai_chat','search','pdf','doc','code','media',
     'idle','locked','manual')),
  exe TEXT,
  app_name TEXT,
  window_title TEXT,
  url TEXT,
  domain TEXT,
  detail TEXT,
  category_id INTEGER REFERENCES categories(id),
  project_id  INTEGER REFERENCES projects(id),
  classified_by TEXT CHECK (classified_by IN ('rule','ai','user') OR classified_by IS NULL),
  rule_id INTEGER,
  ai_confidence REAL,
  edited INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_spans_time ON spans(start_ts);
CREATE INDEX IF NOT EXISTS idx_spans_cat  ON spans(category_id, start_ts);

CREATE TABLE IF NOT EXISTS rules (
  id INTEGER PRIMARY KEY,
  priority INTEGER NOT NULL DEFAULT 100,
  matcher TEXT NOT NULL CHECK (matcher IN ('exe','domain','url_prefix','title_regex')),
  pattern TEXT NOT NULL,
  kind_hint TEXT,
  category_id INTEGER REFERENCES categories(id),
  project_id INTEGER REFERENCES projects(id),
  source TEXT NOT NULL CHECK (source IN ('seed','learned','user')),
  created_ts INTEGER NOT NULL,
  hit_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS stopwatch_readings (
  id INTEGER PRIMARY KEY,
  ts INTEGER NOT NULL,
  source TEXT NOT NULL,
  label TEXT,
  last_value_s INTEGER NOT NULL,
  event TEXT NOT NULL CHECK (event IN ('paused','closed','reset'))
);

CREATE TABLE IF NOT EXISTS day_summaries (
  date TEXT PRIMARY KEY,
  narrative_md TEXT,
  highlights TEXT,
  suggestions TEXT,
  focus_score REAL,
  category_totals TEXT,
  ai_model TEXT,
  generated_ts INTEGER,
  edited INTEGER NOT NULL DEFAULT 0,
  user_note_md TEXT
);

CREATE TABLE IF NOT EXISTS goals (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  period TEXT NOT NULL CHECK (period IN ('daily','weekly','monthly','yearly')),
  direction TEXT NOT NULL CHECK (direction IN ('at_least','at_most')),
  target_minutes INTEGER NOT NULL,
  category_id INTEGER REFERENCES categories(id),
  project_id INTEGER REFERENCES projects(id),
  active_days TEXT,
  created_ts INTEGER NOT NULL,
  archived INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS goal_progress (
  goal_id INTEGER NOT NULL REFERENCES goals(id),
  period_start TEXT NOT NULL,
  minutes INTEGER NOT NULL,
  met INTEGER NOT NULL,
  computed_ts INTEGER NOT NULL,
  PRIMARY KEY (goal_id, period_start)
);

CREATE TABLE IF NOT EXISTS ai_queue (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,
  payload TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0,
  last_error TEXT,
  created_ts INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS edits_audit (
  id INTEGER PRIMARY KEY,
  ts INTEGER NOT NULL,
  entity TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  field TEXT NOT NULL,
  old_value TEXT,
  new_value TEXT
);

CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
"""

# --- §4.3 seed categories: (name, color_slot, is_productive) -----------------
SEED_CATEGORIES = [
    ("Agency (DevsCrest)", 1, 1),
    ("College", 2, 1),
    ("Dual Degree", 3, 1),
    ("Placements", 4, 1),
    ("Building (own products)", 5, 1),
    ("Personal Growth", 6, 1),
    ("Entertainment", 7, 0),
    ("Social & Comms", 8, 0),
]

# --- §8.4 seed rules: (matcher, pattern, kind_hint, category_name) -----------
# category_name None => leave category to AI/user (ambiguous surface).
SEED_RULES = [
    # domains -> Building · code
    ("domain", "github.com", "code", "Building (own products)"),
    ("domain", "vercel.com", "code", "Building (own products)"),
    ("domain", "supabase.com", "code", "Building (own products)"),
    # YouTube: kind only, category ambiguous
    ("domain", "youtube.com", "youtube", None),
    # AI chat hosts: kind only
    ("domain", "chatgpt.com", "ai_chat", None),
    ("domain", "claude.ai", "ai_chat", None),
    ("domain", "gemini.google.com", "ai_chat", None),
    ("domain", "perplexity.ai", "ai_chat", None),
    ("domain", "groq.com", "ai_chat", None),
    # Placements
    ("domain", "linkedin.com", None, "Placements"),
    ("domain", "naukri.com", None, "Placements"),
    ("domain", "internshala.com", None, "Placements"),
    ("domain", "unstop.com", None, "Placements"),
    # Social & Comms
    ("domain", "mail.google.com", None, "Social & Comms"),
    ("domain", "web.whatsapp.com", None, "Social & Comms"),
    ("domain", "instagram.com", None, "Social & Comms"),
    ("domain", "x.com", None, "Social & Comms"),
    # Entertainment
    ("domain", "netflix.com", None, "Entertainment"),
    ("domain", "primevideo.com", None, "Entertainment"),
    ("domain", "hotstar.com", None, "Entertainment"),
    # editors -> Building · code
    ("exe", "Code.exe", "code", "Building (own products)"),
    ("exe", "windsurf.exe", "code", "Building (own products)"),
    ("exe", "cursor.exe", "code", "Building (own products)"),
    # office docs -> kind doc, category via title/AI
    ("exe", "WINWORD.EXE", "doc", None),
    ("exe", "EXCEL.EXE", "doc", None),
    ("exe", "POWERPNT.EXE", "doc", None),
    # pdf readers
    ("exe", "AcroRd32.exe", "pdf", None),
    ("exe", "Acrobat.exe", "pdf", None),
    ("exe", "SumatraPDF.exe", "pdf", None),
    # media players -> Entertainment
    ("exe", "vlc.exe", "media", "Entertainment"),
    ("exe", "Spotify.exe", "media", "Entertainment"),
    # title keyword rules
    ("title_regex", r"(?i)placement|resume|interview|aptitude", None, "Placements"),
    ("title_regex", r"(?i)devscrest|client|proposal|invoice", None, "Agency (DevsCrest)"),
]


def connect(path: Path | None = None) -> sqlite3.Connection:
    """Open a connection with the pragmas Sanjaya relies on everywhere."""
    path = path or paths.DB_PATH
    paths.ensure_dirs()
    conn = sqlite3.connect(str(path), timeout=5.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def get_meta(conn: sqlite3.Connection, key: str, default=None):
    row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_meta(conn: sqlite3.Connection, key: str, value) -> None:
    conn.execute(
        "INSERT INTO meta(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )


def get_setting(conn: sqlite3.Connection, key: str, default=None):
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value) -> None:
    conn.execute(
        "INSERT INTO settings(key,value) VALUES(?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, str(value)),
    )


def _seed(conn: sqlite3.Connection) -> None:
    """Seed categories then rules, only when tables are empty (idempotent)."""
    have_cats = conn.execute("SELECT COUNT(*) c FROM categories").fetchone()["c"]
    if not have_cats:
        for i, (name, slot, prod) in enumerate(SEED_CATEGORIES):
            conn.execute(
                "INSERT INTO categories(name,color_slot,is_productive,sort) "
                "VALUES(?,?,?,?)",
                (name, slot, prod, i),
            )
    have_rules = conn.execute("SELECT COUNT(*) c FROM rules").fetchone()["c"]
    if not have_rules:
        ts = now_ts()
        cat_id = {
            r["name"]: r["id"]
            for r in conn.execute("SELECT id,name FROM categories")
        }
        for matcher, pattern, kind_hint, cat_name in SEED_RULES:
            conn.execute(
                "INSERT INTO rules(priority,matcher,pattern,kind_hint,"
                "category_id,source,created_ts) VALUES(?,?,?,?,?,?,?)",
                (100, matcher, pattern, kind_hint,
                 cat_id.get(cat_name) if cat_name else None, "seed", ts),
            )


def migrate(conn: sqlite3.Connection) -> None:
    """Apply the base schema and any future migrations, then record the version."""
    conn.executescript(SCHEMA_SQL)          # idempotent (all CREATE ... IF NOT EXISTS)
    _current = get_meta(conn, "schema_version")
    # Future: if _current is not None and int(_current) < N, run migration N here.
    _seed(conn)
    set_meta(conn, "schema_version", SCHEMA_VERSION)


def init_db(path: Path | None = None) -> Path:
    """Create/migrate the database file, returning its path."""
    path = path or paths.DB_PATH
    conn = connect(path)
    try:
        migrate(conn)
    finally:
        conn.close()
    return path


# --- span DAL (used by the collector's span builder, Phase 1) ---------------
_SPAN_COLS = (
    "start_ts", "end_ts", "kind", "exe", "app_name", "window_title",
    "url", "domain", "detail", "category_id", "project_id",
    "classified_by", "rule_id", "ai_confidence", "edited",
)


def insert_span(conn: sqlite3.Connection, span: dict) -> int:
    """Insert a span row; ``detail`` may be a dict (JSON-encoded here)."""
    row = _span_row(span)
    cols = ", ".join(_SPAN_COLS)
    ph = ", ".join("?" for _ in _SPAN_COLS)
    cur = conn.execute(
        f"INSERT INTO spans({cols}) VALUES({ph})",
        tuple(row[c] for c in _SPAN_COLS),
    )
    return int(cur.lastrowid)


def update_span(conn: sqlite3.Connection, span_id: int, span: dict) -> None:
    """Update the mutable fields of an existing span (flush / close)."""
    row = _span_row(span)
    sets = ", ".join(f"{c}=?" for c in _SPAN_COLS)
    conn.execute(
        f"UPDATE spans SET {sets} WHERE id=?",
        (*[row[c] for c in _SPAN_COLS], span_id),
    )


def _span_row(span: dict) -> dict:
    row = {c: span.get(c) for c in _SPAN_COLS}
    if isinstance(row["detail"], (dict, list)):
        row["detail"] = json.dumps(row["detail"], ensure_ascii=False)
    row["edited"] = int(row.get("edited") or 0)
    return row
