"""Dev/QA helper: serve the built dashboard against a seeded DEMO database on
port 8899 — never touches the real data/sanjaya.db. Usage:

    uv run python scripts/preview_server.py [--date YYYY-MM-DD]

Seeds one realistic day (code, college docs, YouTube, AI chat, search,
LinkedIn, WhatsApp, idle/locked gaps), a written journal, two goals, one
stopwatch reading — plus 30 days of history so History/Insights render.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sanjaya import config as configmod, db as dbmod, paths  # noqa: E402
from sanjaya.runtime import RuntimeState  # noqa: E402
from sanjaya.timeutil import day_bounds, local_day, now_ts  # noqa: E402

PORT = 8899


def seed(conn, cfg, date: str) -> None:
    cats = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM categories")}
    lo, _hi = day_bounds(date, cfg.timezone, cfg.day_start_hour)

    def span(h0, m0, h1, m1, kind, cat, exe, app, title, domain=None, detail=None):
        dbmod.insert_span(conn, {
            "start_ts": lo + h0 * 3600 + m0 * 60 - cfg.day_start_hour * 3600,
            "end_ts": lo + h1 * 3600 + m1 * 60 - cfg.day_start_hour * 3600,
            "kind": kind, "exe": exe, "app_name": app, "window_title": title,
            "url": None, "domain": domain, "detail": detail,
            "category_id": cats.get(cat) if cat else None, "project_id": None,
            "classified_by": "rule" if cat else None, "rule_id": None,
            "ai_confidence": None, "edited": 0,
        })

    # NOTE: hours below are local wall-clock (lo already includes day_start_hour).
    span(9, 0, 10, 25, "code", "Building (own products)", "Code.exe", "VS Code",
         "spans.py — sanjaya — Visual Studio Code",
         detail=json.dumps({"file": "spans.py", "project_dir": "sanjaya"}))
    span(10, 25, 10, 32, "web", "Building (own products)", "chrome.exe", "Chrome",
         "sanjaya CI — GitHub", "github.com")
    span(10, 32, 11, 5, "ai_chat", "Building (own products)", "chrome.exe", "Chrome",
         "Recharts stacked bars — Claude", "claude.ai",
         detail=json.dumps({"topic": "Recharts stacked bars"}))
    span(11, 5, 11, 35, "idle", None, None, None, None)
    span(11, 35, 12, 40, "doc", "College", "WINWORD.EXE", "Word",
         "Thermodynamics Assignment.docx - Word",
         detail=json.dumps({"file": "Thermodynamics Assignment.docx"}))
    span(12, 40, 13, 10, "youtube", "Entertainment", "chrome.exe", "Chrome",
         "lofi hip hop radio - YouTube", "youtube.com",
         detail=json.dumps({"video_title": "lofi hip hop radio", "channel": "Lofi Girl"}))
    span(13, 10, 14, 0, "locked", None, None, None, None)
    span(14, 0, 15, 20, "web", "Placements", "chrome.exe", "Chrome",
         "SDE openings — LinkedIn", "linkedin.com")
    span(15, 20, 15, 30, "search", "Placements", "chrome.exe", "Chrome",
         "system design interview questions - Google Search", "google.com",
         detail=json.dumps({"query": "system design interview questions"}))
    span(15, 30, 17, 45, "pdf", "Placements", "SumatraPDF.exe", "Sumatra",
         "Cracking the Coding Interview.pdf",
         detail=json.dumps({"file": "Cracking the Coding Interview.pdf"}))
    span(17, 45, 18, 5, "web", "Social & Comms", "chrome.exe", "Chrome",
         "WhatsApp", "web.whatsapp.com")
    span(18, 5, 19, 30, "code", "Agency (DevsCrest)", "Code.exe", "VS Code",
         "invoice.tsx — luxxuro — Visual Studio Code",
         detail=json.dumps({"file": "invoice.tsx", "project_dir": "luxxuro"}))
    span(19, 30, 20, 0, "web", None, "chrome.exe", "Chrome",  # uncategorized leak
         "Notion — Weekly planning", "notion.so")
    # low-confidence AI guess → lands in the Review queue (§10.5)
    dbmod.insert_span(conn, {
        "start_ts": lo + 20 * 3600 + 5 * 60 - cfg.day_start_hour * 3600,
        "end_ts": lo + 20 * 3600 + 35 * 60 - cfg.day_start_hour * 3600,
        "kind": "web", "exe": "chrome.exe", "app_name": "Chrome",
        "window_title": "The Pragmatic Engineer", "url": None, "domain": "substack.com",
        "detail": None, "category_id": cats["Personal Growth"], "project_id": None,
        "classified_by": "ai", "rule_id": None, "ai_confidence": 0.55, "edited": 0,
    })

    # goals (§10.1 meters, §10.4 cards) — created ~40 days back so streaks and
    # history strips have real shape (Phase 8)
    created = now_ts() - 40 * 86400
    for name, period, direction, target, cat in [
        ("≥3h Placements", "daily", "at_least", 180, cats["Placements"]),
        ("≤1.5h Entertainment", "daily", "at_most", 90, cats["Entertainment"]),
        ("10h Agency / week", "weekly", "at_least", 600, cats["Agency (DevsCrest)"]),
    ]:
        conn.execute(
            "INSERT INTO goals(name, period, direction, target_minutes, category_id, created_ts) "
            "VALUES(?, ?, ?, ?, ?, ?)", (name, period, direction, target, cat, created))

    # stopwatch reading
    conn.execute(
        "INSERT INTO stopwatch_readings(ts, source, label, last_value_s, event) "
        "VALUES(?, 'windows_clock', 'Pomodoro', 1500, 'paused')",
        (lo + 16 * 3600 - cfg.day_start_hour * 3600,))

    # journal for the demo day
    conn.execute(
        "INSERT INTO day_summaries(date, narrative_md, highlights, suggestions, focus_score, "
        "category_totals, ai_model, generated_ts) VALUES(?,?,?,?,?,?,?,?)",
        (date,
         "A strong placements-heavy day. You opened with a deep 85-minute block on "
         "**spans.py** in the sanjaya project, then cleared a College assignment before "
         "lunch. The afternoon belonged to **Placements** — LinkedIn scouting, a system "
         "design search, and over two hours inside *Cracking the Coding Interview*. A "
         "short lofi break kept Entertainment inside its cap, and you closed the evening "
         "shipping invoice work for the agency.",
         json.dumps(["85-min deep block on sanjaya spans.py",
                     "Thermodynamics assignment finished",
                     "2h15m focused PDF study for placements",
                     "Agency invoice component shipped"]),
         json.dumps(["Start the LinkedIn pass before noon — your afternoon energy is better spent on the PDF.",
                     "Queue tomorrow's college reading tonight."]),
         76.0, json.dumps({}), "llama-3.3-70b-versatile", now_ts()))

    # 30 days of history so History/Insights have shape
    rng = random.Random(7)
    d0 = datetime.strptime(date, "%Y-%m-%d")
    for i in range(1, 31):
        d = (d0 - timedelta(days=i)).strftime("%Y-%m-%d")
        dlo = day_bounds(d, cfg.timezone, cfg.day_start_hour)[0]
        t = dlo + 5 * 3600
        for cat, base in [("Agency (DevsCrest)", 2.0), ("College", 1.2), ("Placements", 2.5),
                          ("Building (own products)", 1.5), ("Entertainment", 1.0)]:
            hrs = max(0.0, rng.gauss(base, base * 0.5))
            if hrs < 0.2:
                continue
            secs = int(hrs * 3600)
            dbmod.insert_span(conn, {
                "start_ts": t, "end_ts": t + secs, "kind": "app", "exe": "x.exe",
                "app_name": cat, "window_title": cat, "url": None,
                "domain": "youtube.com" if cat == "Entertainment" else None,
                "detail": None, "category_id": cats[cat], "project_id": None,
                "classified_by": "rule", "rule_id": None, "ai_confidence": None, "edited": 0,
            })
            t += secs + 300
    conn.commit()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None)
    args = ap.parse_args()

    import uvicorn

    cfg = configmod.load(create=False)
    date = args.date or local_day(now_ts(), cfg.timezone, cfg.day_start_hour)

    tmp = Path(tempfile.mkdtemp(prefix="sanjaya-preview-"))
    paths.DB_PATH = tmp / "preview.db"  # never the real DB
    dbmod.init_db()
    conn = dbmod.connect()
    seed(conn, cfg, date)
    conn.close()

    from sanjaya.server.app import create_app
    state = RuntimeState()
    state.mark_tick(now_ts())
    app = create_app(cfg, state, controller=None)
    print(f"preview: http://127.0.0.1:{PORT}  (demo day {date}, db {paths.DB_PATH})")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
