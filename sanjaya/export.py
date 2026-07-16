"""JSON/CSV/Markdown exporters (PRD §10.6, Phase 9).

Exports are generated from SQLite on demand and contain only local data. JSON is
machine-readable, CSV is span-oriented, Markdown is a human journal page.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timedelta

from .timeutil import day_bounds


def _dates(start: str, end: str):
    cur = datetime.strptime(start, "%Y-%m-%d").date()
    last = datetime.strptime(end, "%Y-%m-%d").date()
    while cur <= last:
        yield cur.strftime("%Y-%m-%d")
        cur += timedelta(days=1)


def _span_rows(conn, lo: int, hi: int):
    return conn.execute(
        "SELECT s.id, s.start_ts, s.end_ts, s.duration_s, s.kind, s.exe, s.app_name, "
        "s.window_title, s.domain, s.detail, s.category_id, c.name category, "
        "s.project_id, p.name project, s.classified_by, s.ai_confidence, s.edited "
        "FROM spans s LEFT JOIN categories c ON c.id=s.category_id "
        "LEFT JOIN projects p ON p.id=s.project_id "
        "WHERE s.start_ts < ? AND s.end_ts > ? ORDER BY s.start_ts",
        (hi, lo),
    ).fetchall()


def json_export(conn, cfg, start: str, end: str) -> str:
    lo, _ = day_bounds(start, cfg.timezone, cfg.day_start_hour)
    _, hi = day_bounds(end, cfg.timezone, cfg.day_start_hour)
    spans = [dict(r) for r in _span_rows(conn, lo, hi)]
    summaries = [dict(r) for r in conn.execute(
        "SELECT * FROM day_summaries WHERE date >= ? AND date <= ? ORDER BY date", (start, end)
    ).fetchall()]
    goals = [dict(r) for r in conn.execute("SELECT * FROM goals ORDER BY id").fetchall()]
    return json.dumps({"from": start, "to": end, "spans": spans, "summaries": summaries, "goals": goals},
                      ensure_ascii=False, indent=2)


def csv_export(conn, cfg, start: str, end: str) -> str:
    lo, _ = day_bounds(start, cfg.timezone, cfg.day_start_hour)
    _, hi = day_bounds(end, cfg.timezone, cfg.day_start_hour)
    out = io.StringIO()
    fields = ["id", "start_ts", "end_ts", "duration_s", "kind", "app_name", "window_title",
              "domain", "category", "project", "classified_by", "ai_confidence", "edited"]
    w = csv.DictWriter(out, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    for r in _span_rows(conn, lo, hi):
        w.writerow(dict(r))
    return out.getvalue()


def markdown_export(conn, cfg, start: str, end: str) -> str:
    parts: list[str] = [f"# Sanjaya export · {start}" + (f" to {end}" if end != start else "")]
    for d in _dates(start, end):
        lo, hi = day_bounds(d, cfg.timezone, cfg.day_start_hour)
        summary = conn.execute("SELECT * FROM day_summaries WHERE date=?", (d,)).fetchone()
        spans = _span_rows(conn, lo, hi)
        parts.append(f"\n## {d}\n")
        if summary and summary["narrative_md"]:
            parts.append(summary["narrative_md"].strip())
            parts.append("")
        if summary and summary["highlights"]:
            try:
                highlights = json.loads(summary["highlights"])
            except (TypeError, ValueError):
                highlights = []
            if highlights:
                parts.append("### Highlights")
                parts.extend(f"- {h}" for h in highlights)
                parts.append("")
        totals: dict[str, int] = {}
        for r in spans:
            key = r["category"] or "Uncategorized"
            totals[key] = totals.get(key, 0) + int(r["duration_s"] or 0)
        if totals:
            parts.append("### Time by category")
            for name, sec in sorted(totals.items(), key=lambda kv: -kv[1]):
                h, m = divmod(sec // 60, 60)
                parts.append(f"- **{name}:** {h}h {m:02d}m")
            parts.append("")
        if summary and summary["user_note_md"]:
            parts.append("### Notes")
            parts.append(summary["user_note_md"].strip())
    return "\n".join(parts).strip() + "\n"


def render(conn, cfg, fmt: str, start: str, end: str) -> tuple[str, str, str]:
    if fmt == "json":
        return json_export(conn, cfg, start, end), "application/json", f"sanjaya-{start}-{end}.json"
    if fmt == "csv":
        return csv_export(conn, cfg, start, end), "text/csv", f"sanjaya-spans-{start}-{end}.csv"
    if fmt in ("md", "markdown"):
        return markdown_export(conn, cfg, start, end), "text/markdown", f"sanjaya-journal-{start}-{end}.md"
    raise ValueError("format must be json, csv, or md")
