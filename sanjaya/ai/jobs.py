"""AI jobs (PRD §9.3): the classifier that fills unknown spans' categories, plus
(Phase 5) the daily-journal and weekly-insight writers. Each job is pure with
respect to the DB + an injected client, so tests drive them with a fake client
and never touch the live Groq endpoint (§15).
"""
from __future__ import annotations

import json

from ..db import get_setting
from ..log import get
from ..timeutil import now_ts
from . import budget, prompts

_log = get("ai.jobs")

CLASSIFY_CONFIDENCE_MIN = 0.6      # >= applies as classified_by='ai'; below -> Review (§9.3)
CLASSIFY_BATCH = 40                # <=40 unknown spans per request (§9.3 A)
MAX_ATTEMPTS = 10                  # queue item gives up after this many tries (§9.1)


def _model(conn, cfg, key: str, default: str) -> str:
    """Model names are config defaults, overridable live from Settings (Phase 9)."""
    return str(get_setting(conn, key, None) or cfg.get("ai", key, default))


# --- helpers -----------------------------------------------------------------
def _ph(seq) -> str:
    return ", ".join("?" for _ in seq)


def _categories(conn) -> list[tuple[int, str]]:
    rows = conn.execute(
        "SELECT id, name FROM categories WHERE archived=0 ORDER BY sort"
    ).fetchall()
    return [(r["id"], r["name"]) for r in rows]


def _projects_by_category(conn) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for r in conn.execute(
        "SELECT c.name AS cat, p.name AS proj FROM projects p "
        "JOIN categories c ON c.id = p.category_id WHERE p.archived=0"
    ):
        out.setdefault(r["cat"], []).append(r["proj"])
    return out


_DETAIL_KEYS = ("video_title", "channel", "query", "topic", "file",
                "project_dir", "page_title", "folder", "app")


def _compact_detail(detail_json) -> str:
    if not detail_json:
        return ""
    try:
        d = json.loads(detail_json) if isinstance(detail_json, str) else dict(detail_json)
    except (ValueError, TypeError):
        return ""
    return "; ".join(f"{k}={d[k]}" for k in _DETAIL_KEYS if d.get(k))


def _build_records(spans: list[dict]) -> list[dict]:
    return [{
        "i": i,
        "app_name": s.get("app_name"),
        "kind": s.get("kind"),
        "title": s.get("window_title"),
        "domain": s.get("domain"),          # domain only — never the full URL (§9.2)
        "detail_compact": _compact_detail(s.get("detail")),
    } for i, s in enumerate(spans)]


def _resolve_project(conn, category_id: int, name) -> int | None:
    """Map a classifier-returned project name to an EXISTING project id under the
    category. Never auto-creates — the AI must not invent taxonomy."""
    if not name:
        return None
    row = conn.execute(
        "SELECT id FROM projects WHERE category_id=? AND name=? AND archived=0",
        (category_id, name),
    ).fetchone()
    return row["id"] if row else None


def _apply(conn, spans: list[dict], name_to_id: dict[str, int], data) -> int:
    """Apply classifications >= confidence floor. Never overrides a span that has
    since been categorized by a rule or the user (guarded in the UPDATE)."""
    if not data:
        return 0
    applied = 0
    for c in data.get("classifications") or []:
        idx = c.get("i")
        if idx is None or idx < 0 or idx >= len(spans):
            continue
        cat = c.get("category")
        conf = float(c.get("confidence") or 0.0)
        if conf < CLASSIFY_CONFIDENCE_MIN or cat not in name_to_id:
            continue
        cid = name_to_id[cat]
        pid = _resolve_project(conn, cid, c.get("project"))
        cur = conn.execute(
            "UPDATE spans SET category_id=?, project_id=?, classified_by='ai', "
            "ai_confidence=? WHERE id=? AND category_id IS NULL AND classified_by IS NULL",
            (cid, pid, conf, spans[idx]["id"]),
        )
        if cur.rowcount:
            applied += 1
    return applied


def _mark_done(conn, ids) -> None:
    conn.execute(f"UPDATE ai_queue SET status='done' WHERE id IN ({_ph(ids)})", ids)


def _requeue(conn, ids, err: str) -> None:
    """Bump attempts, keep the payload; give up to 'failed' only past MAX_ATTEMPTS."""
    conn.execute(
        f"UPDATE ai_queue SET status='pending', attempts=attempts+1, last_error=? "
        f"WHERE id IN ({_ph(ids)})", (err[:500], *ids),
    )
    conn.execute(
        f"UPDATE ai_queue SET status='failed' WHERE id IN ({_ph(ids)}) "
        f"AND attempts >= {MAX_ATTEMPTS}", ids,
    )


# --- the classify job --------------------------------------------------------
def run_classify_batch(conn, client, cfg, *, batch_size: int = CLASSIFY_BATCH) -> dict:
    """Classify one batch of pending 'classify' queue items. Returns a summary
    dict. Raises on a client/API failure AFTER the batch has been re-queued (so
    the scheduler counts it as a failed run but never loses work)."""
    rows = conn.execute(
        "SELECT id, payload FROM ai_queue WHERE kind='classify' AND status='pending' "
        "ORDER BY id LIMIT ?", (batch_size,),
    ).fetchall()
    if not rows:
        return {"picked": 0, "classified": 0, "skipped": 0}

    ids = [r["id"] for r in rows]

    if budget.over_cap(conn, cfg):
        _log.info("AI daily token cap reached; classify paused")
        return {"picked": 0, "classified": 0, "skipped": len(ids), "paused": True}

    span_ids = []
    for r in rows:
        try:
            sid = json.loads(r["payload"]).get("span_id")
        except (ValueError, TypeError):
            sid = None
        if sid is not None:
            span_ids.append(sid)

    conn.execute(f"UPDATE ai_queue SET status='running' WHERE id IN ({_ph(ids)})", ids)
    try:
        spans: list[dict] = []
        if span_ids:
            rows2 = conn.execute(
                f"SELECT * FROM spans WHERE id IN ({_ph(span_ids)}) "
                f"AND category_id IS NULL AND classified_by IS NULL", span_ids,
            ).fetchall()
            spans = [dict(r) for r in rows2 if (r["window_title"] or "") != "[excluded]"]

        if not spans:
            _mark_done(conn, ids)
            return {"picked": len(ids), "classified": 0, "skipped": len(ids)}

        cats = _categories(conn)
        names = [n for _, n in cats]
        name_to_id = {n: i for i, n in cats}
        system, user = prompts.classifier(
            names, _projects_by_category(conn), _build_records(spans),
            cfg.get("ai", "user_context", None),
        )
        out = client.complete(
            conn, kind="classify",
            model=_model(conn, cfg, "classify_model", "llama-3.1-8b-instant"),
            system=system, user=user, json_mode=True, temperature=0.2,
        )
        classified = _apply(conn, spans, name_to_id, out.get("data"))
        _mark_done(conn, ids)
        return {"picked": len(ids), "classified": classified,
                "skipped": len(ids) - len(spans)}
    except Exception as e:  # noqa: BLE001 - requeue then propagate
        _requeue(conn, ids, str(e))
        raise


# --- daily journal (§9.3 B) --------------------------------------------------
QUIET_DAY_MD = (
    "A quiet day. Sanjaya recorded no tracked screen activity for this date — "
    "the machine was likely off, or you were away from it. Nothing to report, "
    "and that's perfectly fine. If you did offline work worth remembering, add "
    "it with **+ Add block**."
)
QUIET_DAY_SUGGESTIONS = [
    "Log any offline work (class, meetings, gym) with + Add block so the day is complete.",
]


def _upsert_day_deterministic(conn, date: str, payload: dict) -> None:
    """Persist the deterministic parts (focus score + category totals) so the
    dashboard shows real data even when AI is unavailable (§13.6)."""
    conn.execute(
        "INSERT INTO day_summaries(date, focus_score, category_totals) VALUES(?,?,?) "
        "ON CONFLICT(date) DO UPDATE SET focus_score=excluded.focus_score, "
        "category_totals=excluded.category_totals",
        (date, payload["focus_score"], json.dumps(payload["category_totals_map"])),
    )


def _store_narrative(conn, date: str, narrative_md: str, highlights, suggestions,
                     model: str | None) -> None:
    conn.execute(
        "UPDATE day_summaries SET narrative_md=?, highlights=?, suggestions=?, "
        "ai_model=?, generated_ts=?, edited=0 WHERE date=?",
        (narrative_md, json.dumps(highlights or []), json.dumps(suggestions or []),
         model, now_ts(), date),
    )


def summarize_day(conn, client, cfg, date: str, *, force: bool = False) -> dict:
    """Generate (or refresh) the daily journal for ``date`` (§9.3 B).

    Focus score + category totals are always persisted first. A day with zero
    tracked activity gets a deterministic 'quiet day' entry — no AI call. An
    existing narrative is left alone unless ``force`` (the Regenerate path)."""
    from .. import reporting

    payload = reporting.build_day_payload(conn, cfg, date)
    _upsert_day_deterministic(conn, date, payload)

    have = conn.execute(
        "SELECT narrative_md FROM day_summaries WHERE date=?", (date,)
    ).fetchone()
    if have and have["narrative_md"] and not force:
        return {"date": date, "status": "exists", "payload": payload}

    if not payload["has_activity"]:
        _store_narrative(conn, date, QUIET_DAY_MD, [], QUIET_DAY_SUGGESTIONS, None)
        return {"date": date, "status": "quiet", "payload": payload}

    model = _model(conn, cfg, "narrative_model", "llama-3.3-70b-versatile")
    system, user = prompts.daily_journal(payload)
    out = client.complete(conn, kind="summarize_day", model=model,
                          system=system, user=user, json_mode=True, temperature=0.5)
    data = out.get("data") or {}
    _store_narrative(
        conn, date,
        data.get("narrative_md") or QUIET_DAY_MD,
        data.get("highlights") or [],
        data.get("suggestions") or [],
        model,
    )
    return {"date": date, "status": "generated", "payload": payload, "data": data}


# --- weekly insight (§9.3 C) -------------------------------------------------
def weekly_insight(conn, client, cfg, week_start: str, *, force: bool = False) -> dict:
    """Generate the weekly insight for the Mon-anchored ``week_start`` and cache
    it in ``settings`` (there is no weekly table in the schema)."""
    from .. import reporting
    from ..db import get_setting, set_setting

    key = f"weekly_{week_start}"
    if not force:
        cached = get_setting(conn, key, None)
        if cached:
            return json.loads(cached)

    model = _model(conn, cfg, "narrative_model", "llama-3.3-70b-versatile")
    payload = reporting.build_week_payload(conn, cfg, week_start)
    system, user = prompts.weekly_insight(payload)
    out = client.complete(conn, kind="weekly_insight", model=model,
                          system=system, user=user, json_mode=True, temperature=0.5)
    data = out.get("data") or {}
    record = {
        "week_start": week_start,
        "generated_ts": now_ts(),
        "insight_md": data.get("insight_md", ""),
        "wins": data.get("wins", []),
        "leaks": data.get("leaks", []),
        "next_week_focus": data.get("next_week_focus", []),
    }
    set_setting(conn, key, json.dumps(record))
    return record
