"""JSON API under ``/api`` (PRD §10.7). Localhost-only. Phase 3 ships the
collector/extension health surface (``/status``) plus tray-parity tracking
controls; later phases extend this router (journal, insights, goals, editing).

Handlers are synchronous and open a short-lived SQLite connection per request
(WAL makes this cheap and avoids cross-thread connection sharing).
"""
from __future__ import annotations

import json

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request, Response

from .. import __version__, autostart, db as dbmod, export as exportmod, goals as goalsmod, metrics, paths, privacy, reporting
from .. import env
from ..ai import jobs
from ..ai.groq_client import GroqClient, GroqError
from ..timeutil import day_bounds, local_day, now_ts

router = APIRouter(prefix="/api")

_COLLECTOR_ALIVE_S = 30   # a tick within this window means the loop is healthy


def _today(cfg) -> str:
    return local_day(now_ts(), cfg.timezone, cfg.day_start_hour)


def _summary_dict(row) -> dict:
    def _json(v, default):
        try:
            return json.loads(v) if v else default
        except (ValueError, TypeError):
            return default
    return {
        "date": row["date"],
        "exists": True,
        "narrative_md": row["narrative_md"],
        "highlights": _json(row["highlights"], []),
        "suggestions": _json(row["suggestions"], []),
        "focus_score": row["focus_score"],
        "category_totals": _json(row["category_totals"], {}),
        "ai_model": row["ai_model"],
        "generated_ts": row["generated_ts"],
        "edited": bool(row["edited"]),
        "user_note_md": row["user_note_md"],
    }


def _audit(conn, entity, entity_id, field, old, new) -> None:
    conn.execute(
        "INSERT INTO edits_audit(ts, entity, entity_id, field, old_value, new_value) "
        "VALUES(?,?,?,?,?,?)",
        (now_ts(), entity, str(entity_id), field,
         None if old is None else str(old), None if new is None else str(new)),
    )


_JSON_SETTING_KEYS = {"exclude_exes", "exclude_domains", "redaction_patterns", "pause_schedule"}
_BOOL_SETTING_KEYS = {"debug_ai_payloads", "texture_fills", "onboarding_done"}
_INT_SETTING_KEYS = {"retention_months", "ai_daily_token_cap"}
_STR_SETTING_KEYS = {"classify_model", "narrative_model", "summary_time"}


def _setting_value(conn, cfg, key: str):
    raw = dbmod.get_setting(conn, key, None)
    if key in _JSON_SETTING_KEYS:
        default = privacy.default_settings_payload().get(key, []) if key != "pause_schedule" else []
        if raw is None:
            return default
        try:
            val = json.loads(raw)
            return val if isinstance(val, list) else default
        except (TypeError, ValueError):
            return default
    if key in _BOOL_SETTING_KEYS:
        if raw is None:
            return bool(cfg.get("ai", key, False)) if key == "debug_ai_payloads" else False
        return str(raw).lower() in ("1", "true", "yes", "on")
    if key in _INT_SETTING_KEYS:
        if raw is None:
            if key == "retention_months":
                return int(cfg.get("privacy", key, 0))
            return int(cfg.get("ai", key, 300000))
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0
    if key in _STR_SETTING_KEYS:
        section = "ai"
        return raw if raw is not None else cfg.get(section, key, "")
    return raw


def _set_setting(conn, key: str, value) -> None:
    if key in _JSON_SETTING_KEYS:
        if not isinstance(value, list):
            raise HTTPException(status_code=422, detail=f"{key} must be a list")
        dbmod.set_setting(conn, key, json.dumps(value, ensure_ascii=False))
    elif key in _BOOL_SETTING_KEYS:
        dbmod.set_setting(conn, key, "1" if bool(value) else "0")
    elif key in _INT_SETTING_KEYS:
        try:
            iv = int(value)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail=f"{key} must be an integer")
        if iv < 0:
            raise HTTPException(status_code=422, detail=f"{key} must be >= 0")
        dbmod.set_setting(conn, key, str(iv))
    elif key in _STR_SETTING_KEYS:
        dbmod.set_setting(conn, key, str(value or "").strip())
    else:
        raise HTTPException(status_code=422, detail=f"unknown setting: {key}")


@router.get("/status")
def status(request: Request):
    """Collector heartbeat, extension last-seen, ai_queue depth, version (§10.6)."""
    rt = request.app.state.rt
    ctrl = request.app.state.controller
    now = now_ts()
    last_tick = rt.last_tick_ts
    last_ext = rt.last_ext_ts

    conn = dbmod.connect()
    try:
        pending = conn.execute(
            "SELECT COUNT(*) c FROM ai_queue WHERE status='pending'"
        ).fetchone()["c"]
        failed = conn.execute(
            "SELECT COUNT(*) c FROM ai_queue WHERE status='failed'"
        ).fetchone()["c"]
        spans_total = conn.execute("SELECT COUNT(*) c FROM spans").fetchone()["c"]
    finally:
        conn.close()

    cfg = request.app.state.cfg
    db_bytes = paths.DB_PATH.stat().st_size if paths.DB_PATH.exists() else 0
    return {
        "version": __version__,
        "now_ts": now,
        "today": _today(cfg),
        "timezone": cfg.timezone,
        "day_start_hour": cfg.day_start_hour,
        "collector": {
            "alive": bool(last_tick) and (now - last_tick) <= _COLLECTOR_ALIVE_S,
            "last_tick_ts": last_tick or None,
            "last_tick_age_s": (now - last_tick) if last_tick else None,
            "paused": bool(ctrl.is_paused()) if ctrl is not None else False,
        },
        "extension": {
            "last_seen_ts": last_ext or None,
            "last_seen_age_s": (now - last_ext) if last_ext else None,
        },
        "ai_queue": {"pending": pending, "failed": failed},
        "process": metrics.self_metrics(),
        "autostart": {"enabled": autostart.enabled()},
        "data_dir": str(paths.DATA_DIR),
        "exports_dir": str(paths.EXPORT_DIR),
        "spans_total": spans_total,
        "db_bytes": db_bytes,
    }


@router.post("/autostart")
def set_autostart(body: dict):
    """Start-with-Windows toggle (Settings + tray parity, §11)."""
    enabled = bool(body.get("enabled"))
    ok = autostart.enable() if enabled else autostart.disable()
    if not ok:
        raise HTTPException(status_code=500, detail="could not update Startup shortcut")
    return {"enabled": autostart.enabled()}


@router.post("/pause")
def pause(request: Request, body: dict | None = None):
    """Pause tracking (tray parity, §10.7). ``{"minutes": N}``; null = rest of day."""
    ctrl = request.app.state.controller
    minutes = (body or {}).get("minutes")
    if ctrl is not None:
        ctrl.pause(int(minutes) if minutes is not None else None)
    return {"paused": True, "minutes": minutes}


@router.post("/resume")
def resume(request: Request):
    ctrl = request.app.state.controller
    if ctrl is not None:
        ctrl.resume()
    return {"paused": False}


# --- day view (read; §10.7) --------------------------------------------------
@router.get("/day/{date}")
def get_day(date: str, request: Request):
    """Deterministic day view: spans, category totals, focus score, summary.
    Works with zero AI (§13.6)."""
    cfg = request.app.state.cfg
    conn = dbmod.connect()
    try:
        payload = reporting.build_day_payload(conn, cfg, date)
        lo, hi = day_bounds(date, cfg.timezone, cfg.day_start_hour)
        rows = conn.execute(
            "SELECT id, start_ts, end_ts, kind, exe, app_name, window_title, domain, "
            "url, detail, category_id, project_id, classified_by, ai_confidence, edited "
            "FROM spans WHERE start_ts < ? AND end_ts > ? ORDER BY start_ts", (hi, lo),
        ).fetchall()
        srow = conn.execute("SELECT * FROM day_summaries WHERE date=?", (date,)).fetchone()
        swrows = conn.execute(
            "SELECT ts, source, label, last_value_s, event FROM stopwatch_readings "
            "WHERE ts >= ? AND ts < ? ORDER BY ts", (lo, hi),
        ).fetchall()
    finally:
        conn.close()
    return {
        "date": date,
        "active_seconds": payload["active_seconds"],
        "idle_seconds": payload["idle_seconds"],
        "focus_score": payload["focus_score"],
        "focus_components": payload["focus_components"],
        "category_totals": payload["category_totals_map"],
        "spans": [dict(r) for r in rows],
        "goals": payload["goals"],
        "stopwatch": [dict(r) for r in swrows],
        "summary": _summary_dict(srow) if srow else {"date": date, "exists": False},
    }


def _parse_date(s: str, name: str) -> str:
    try:
        return datetime.strptime(s, "%Y-%m-%d").strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail=f"{name} must be YYYY-MM-DD")


_RANGE_MAX_DAYS = 400   # calendar year of heatmap + margin; guards runaway scans


@router.get("/range")
def get_range(request: Request,
              from_: str = Query(alias="from"), to: str = Query(...),
              bucket: str = "day"):
    """Per-day aggregates for History/Insights (§10.7). ``bucket=day`` only."""
    if bucket != "day":
        raise HTTPException(status_code=422, detail="only bucket=day is supported")
    d_from, d_to = _parse_date(from_, "from"), _parse_date(to, "to")
    if d_from > d_to:
        raise HTTPException(status_code=422, detail="from must be <= to")
    n_days = (datetime.strptime(d_to, "%Y-%m-%d") - datetime.strptime(d_from, "%Y-%m-%d")).days + 1
    if n_days > _RANGE_MAX_DAYS:
        raise HTTPException(status_code=422, detail=f"range too large (max {_RANGE_MAX_DAYS} days)")
    cfg = request.app.state.cfg
    conn = dbmod.connect()
    try:
        days = reporting.build_range(conn, cfg, d_from, d_to)
    finally:
        conn.close()
    return {"from": d_from, "to": d_to, "bucket": "day", "days": days}


@router.get("/categories")
def get_categories(include_archived: bool = True):
    """Category taxonomy for rendering and Settings management (§10.6)."""
    conn = dbmod.connect()
    try:
        where = "" if include_archived else "WHERE archived=0"
        rows = conn.execute(
            f"SELECT id, name, color_slot, is_productive, sort, archived "
            f"FROM categories {where} ORDER BY sort, id"
        ).fetchall()
    finally:
        conn.close()
    return {"categories": [dict(r) for r in rows]}


@router.post("/categories")
def create_category(body: dict):
    name = str(body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="name is required")
    slot = body.get("color_slot")
    if slot is not None and (int(slot) < 1 or int(slot) > 8):
        raise HTTPException(status_code=422, detail="color_slot must be 1..8 or null")
    conn = dbmod.connect()
    try:
        try:
            cur = conn.execute(
                "INSERT INTO categories(name,color_slot,is_productive,sort) VALUES(?,?,?,?)",
                (name, slot, int(bool(body.get("is_productive", True))), int(body.get("sort", 999))),
            )
        except Exception:
            raise HTTPException(status_code=409, detail="category already exists")
        cid = int(cur.lastrowid)
        _audit(conn, "category", cid, "create", None, name)
        row = conn.execute("SELECT * FROM categories WHERE id=?", (cid,)).fetchone()
    finally:
        conn.close()
    return {"category": dict(row)}


@router.patch("/categories/{category_id}")
def update_category(category_id: int, body: dict):
    fields = {"name", "color_slot", "is_productive", "sort", "archived"}
    if not fields.intersection(body):
        raise HTTPException(status_code=422, detail="no editable fields supplied")
    conn = dbmod.connect()
    try:
        row = conn.execute("SELECT * FROM categories WHERE id=?", (category_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="category not found")
        updates = {}
        for f in fields:
            if f in body:
                val = body[f]
                if f == "name":
                    val = str(val or "").strip()
                    if not val:
                        raise HTTPException(status_code=422, detail="name is required")
                if f == "color_slot" and val is not None and (int(val) < 1 or int(val) > 8):
                    raise HTTPException(status_code=422, detail="color_slot must be 1..8 or null")
                if f in ("is_productive", "archived"):
                    val = int(bool(val))
                updates[f] = val
                if row[f] != val:
                    _audit(conn, "category", category_id, f, row[f], val)
        sets = ", ".join(f"{f}=?" for f in updates)
        conn.execute(f"UPDATE categories SET {sets} WHERE id=?", (*updates.values(), category_id))
        row = conn.execute("SELECT * FROM categories WHERE id=?", (category_id,)).fetchone()
    finally:
        conn.close()
    return {"category": dict(row)}


# --- projects (popover quick-create + Settings manager; Phase 9) --------------
@router.get("/projects")
def get_projects(include_archived: bool = True):
    conn = dbmod.connect()
    try:
        where = "" if include_archived else "WHERE archived=0"
        rows = conn.execute(
            f"SELECT id, category_id, name, archived FROM projects {where} ORDER BY name"
        ).fetchall()
    finally:
        conn.close()
    return {"projects": [dict(r) for r in rows]}


@router.post("/projects")
def create_project(body: dict):
    name = str(body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="name is required")
    conn = dbmod.connect()
    try:
        _require_category(conn, body.get("category_id"), required=True)
        try:
            cur = conn.execute(
                "INSERT INTO projects(category_id, name) VALUES(?,?)",
                (body["category_id"], name),
            )
        except Exception:
            raise HTTPException(status_code=409, detail="project already exists in that category")
        pid = int(cur.lastrowid)
        _audit(conn, "project", pid, "create", None, f"{name} (cat {body['category_id']})")
        row = conn.execute(
            "SELECT id, category_id, name, archived FROM projects WHERE id=?", (pid,)
        ).fetchone()
    finally:
        conn.close()
    return {"project": dict(row)}


@router.patch("/projects/{project_id}")
def update_project(project_id: int, body: dict):
    conn = dbmod.connect()
    try:
        row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="project not found")
        name = str(body.get("name", row["name"]) or "").strip()
        cat = body.get("category_id", row["category_id"])
        archived = int(bool(body.get("archived", row["archived"])))
        _require_category(conn, cat, required=True)
        for f, old, new in (("name", row["name"], name), ("category_id", row["category_id"], cat),
                            ("archived", row["archived"], archived)):
            if old != new:
                _audit(conn, "project", project_id, f, old, new)
        conn.execute("UPDATE projects SET name=?, category_id=?, archived=? WHERE id=?",
                     (name, cat, archived, project_id))
        row = conn.execute("SELECT id, category_id, name, archived FROM projects WHERE id=?", (project_id,)).fetchone()
    finally:
        conn.close()
    return {"project": dict(row)}


@router.delete("/projects/{project_id}")
def archive_project(project_id: int):
    conn = dbmod.connect()
    try:
        row = conn.execute("SELECT archived FROM projects WHERE id=?", (project_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="project not found")
        _audit(conn, "project", project_id, "archived", row["archived"], 1)
        conn.execute("UPDATE projects SET archived=1 WHERE id=?", (project_id,))
    finally:
        conn.close()
    return {"archived": True, "id": project_id}


# --- rules / settings / exports (§10.6; Phase 9) ------------------------------
@router.get("/rules")
def list_rules():
    conn = dbmod.connect()
    try:
        rows = conn.execute(
            "SELECT r.*, c.name category, p.name project FROM rules r "
            "LEFT JOIN categories c ON c.id=r.category_id "
            "LEFT JOIN projects p ON p.id=r.project_id "
            "ORDER BY priority, matcher, pattern"
        ).fetchall()
    finally:
        conn.close()
    return {"rules": [dict(r) for r in rows]}


@router.post("/rules")
def create_rule(request: Request, body: dict):
    matcher = str(body.get("matcher") or "").strip()
    pattern = str(body.get("pattern") or "").strip()
    if matcher not in ("exe", "domain", "url_prefix", "title_regex"):
        raise HTTPException(status_code=422, detail="invalid matcher")
    if not pattern:
        raise HTTPException(status_code=422, detail="pattern is required")
    conn = dbmod.connect()
    try:
        _require_category(conn, body.get("category_id"))
        _require_project(conn, body.get("project_id"), body.get("category_id"))
        cur = conn.execute(
            "INSERT INTO rules(priority, matcher, pattern, kind_hint, category_id, project_id, source, created_ts) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (int(body.get("priority", 75)), matcher, pattern, body.get("kind_hint"),
             body.get("category_id"), body.get("project_id"), body.get("source", "user"), now_ts()),
        )
        rid = int(cur.lastrowid)
        _audit(conn, "rule", rid, "create", None, f"{matcher}:{pattern}")
        if request.app.state.rt is not None:
            request.app.state.rt.bump_rules()
        row = conn.execute("SELECT * FROM rules WHERE id=?", (rid,)).fetchone()
    finally:
        conn.close()
    return {"rule": dict(row)}


@router.patch("/rules/{rule_id}")
def update_rule(rule_id: int, request: Request, body: dict):
    fields = ("priority", "matcher", "pattern", "kind_hint", "category_id", "project_id")
    conn = dbmod.connect()
    try:
        row = conn.execute("SELECT * FROM rules WHERE id=?", (rule_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="rule not found")
        merged = dict(row)
        for f in fields:
            if f in body:
                merged[f] = body[f]
        if merged["matcher"] not in ("exe", "domain", "url_prefix", "title_regex"):
            raise HTTPException(status_code=422, detail="invalid matcher")
        if not str(merged["pattern"] or "").strip():
            raise HTTPException(status_code=422, detail="pattern is required")
        _require_category(conn, merged.get("category_id"))
        _require_project(conn, merged.get("project_id"), merged.get("category_id"))
        for f in fields:
            if row[f] != merged[f]:
                _audit(conn, "rule", rule_id, f, row[f], merged[f])
        conn.execute(
            "UPDATE rules SET priority=?, matcher=?, pattern=?, kind_hint=?, category_id=?, project_id=? WHERE id=?",
            (int(merged["priority"]), merged["matcher"], str(merged["pattern"]).strip(),
             merged["kind_hint"], merged["category_id"], merged["project_id"], rule_id),
        )
        if request.app.state.rt is not None:
            request.app.state.rt.bump_rules()
        row = conn.execute("SELECT * FROM rules WHERE id=?", (rule_id,)).fetchone()
    finally:
        conn.close()
    return {"rule": dict(row)}


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, request: Request):
    conn = dbmod.connect()
    try:
        row = conn.execute("SELECT matcher, pattern FROM rules WHERE id=?", (rule_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="rule not found")
        _audit(conn, "rule", rule_id, "delete", f"{row['matcher']}:{row['pattern']}", None)
        conn.execute("DELETE FROM rules WHERE id=?", (rule_id,))
        if request.app.state.rt is not None:
            request.app.state.rt.bump_rules()
    finally:
        conn.close()
    return {"deleted": True, "id": rule_id}


@router.get("/settings")
def get_settings(request: Request):
    cfg = request.app.state.cfg
    keys = sorted(_JSON_SETTING_KEYS | _BOOL_SETTING_KEYS | _INT_SETTING_KEYS | _STR_SETTING_KEYS)
    conn = dbmod.connect()
    try:
        settings = {k: _setting_value(conn, cfg, k) for k in keys}
    finally:
        conn.close()
    return {"settings": settings, "data_dir": str(paths.DATA_DIR), "exports_dir": str(paths.EXPORT_DIR)}


@router.patch("/settings")
def patch_settings(request: Request, body: dict):
    cfg = request.app.state.cfg
    conn = dbmod.connect()
    try:
        for k, v in body.items():
            old = _setting_value(conn, cfg, k)
            _set_setting(conn, k, v)
            new = _setting_value(conn, cfg, k)
            if old != new:
                _audit(conn, "settings", k, "value", old, new)
        keys = sorted(_JSON_SETTING_KEYS | _BOOL_SETTING_KEYS | _INT_SETTING_KEYS | _STR_SETTING_KEYS)
        settings = {k: _setting_value(conn, cfg, k) for k in keys}
    finally:
        conn.close()
    return {"settings": settings}


@router.post("/settings/test-ai")
def test_ai(request: Request):
    """Settings → 'Test connection' (§10.6). Verifies key presence and, when a
    key exists, performs one minimal completion against the classify model."""
    cfg = request.app.state.cfg
    if not env.groq_api_key():
        return {"ok": False, "detail": "GROQ_API_KEY not set in .env"}
    conn = dbmod.connect()
    try:
        client = GroqClient(cfg)
        out = client.complete(
            conn, kind="test", model=str(_setting_value(conn, cfg, "classify_model") or
                                         cfg.get("ai", "classify_model", "llama-3.1-8b-instant")),
            system='Reply with JSON only: {"ok": true}', user="ping",
            json_mode=True, temperature=0.0,
        )
        return {"ok": bool((out.get("data") or {}).get("ok")), "total_tokens": out.get("total_tokens", 0)}
    except GroqError as e:
        return {"ok": False, "detail": str(e)}
    finally:
        conn.close()


@router.get("/export")
def export_data(request: Request, format: str = "json", from_: str = Query(alias="from"), to: str = Query(...)):
    d_from, d_to = _parse_date(from_, "from"), _parse_date(to, "to")
    if d_from > d_to:
        raise HTTPException(status_code=422, detail="from must be <= to")
    cfg = request.app.state.cfg
    conn = dbmod.connect()
    try:
        try:
            text, media_type, filename = exportmod.render(conn, cfg, format, d_from, d_to)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
    finally:
        conn.close()
    return Response(text, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# --- span editing (§10.1 popover, §10.7; Phase 7) ------------------------------
_SPAN_VIEW = ("id, start_ts, end_ts, kind, exe, app_name, window_title, domain, "
              "url, detail, category_id, project_id, classified_by, ai_confidence, edited")


def _span_view(conn, span_id: int) -> dict:
    row = conn.execute(f"SELECT {_SPAN_VIEW} FROM spans WHERE id=?", (span_id,)).fetchone()
    return dict(row) if row else {}


def _require_span(conn, span_id: int):
    row = conn.execute("SELECT * FROM spans WHERE id=?", (span_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="span not found")
    return row


def _require_category(conn, cid, required: bool = False) -> None:
    if cid is None:
        if required:
            raise HTTPException(status_code=422, detail="category_id is required")
        return
    if not conn.execute("SELECT id FROM categories WHERE id=?", (cid,)).fetchone():
        raise HTTPException(status_code=422, detail="unknown category_id")


def _require_project(conn, pid, category_id=None) -> None:
    if pid is None:
        return
    row = conn.execute("SELECT id, category_id FROM projects WHERE id=?", (pid,)).fetchone()
    if not row:
        raise HTTPException(status_code=422, detail="unknown project_id")
    if category_id is not None and row["category_id"] != category_id:
        raise HTTPException(status_code=422, detail="project does not belong to that category")


def _merge_label(detail, label) -> str | None:
    """Set/clear a free-text ``label`` inside the span's detail JSON."""
    try:
        d = json.loads(detail) if isinstance(detail, str) and detail else (detail or {})
        if not isinstance(d, dict):
            d = {}
    except (ValueError, TypeError):
        d = {}
    if label:
        d["label"] = str(label)
    else:
        d.pop("label", None)
    return json.dumps(d, ensure_ascii=False) if d else None


def _url_prefix_of(url: str) -> str:
    """Prefix pattern from a URL: strip query + fragment so the rule catches the
    page/section, not one specific visit."""
    for sep in ("?", "#"):
        i = url.find(sep)
        if i != -1:
            url = url[:i]
    return url


def _learn_rule(conn, rt, span: dict, category_id: int, project_id) -> dict | None:
    """§8.4 "always classify like this": create a source='learned' rule from the
    most specific available matcher (url_prefix if URL present, else domain, else
    exe — the single-matcher schema means 'exe+title keyword' degrades to exe),
    priority 50 (beats seeds at 100). Retro-applies to still-unclassified spans
    only (never overrides a user/AI/rule classification), then signals the
    collector thread to reload its engine.
    """
    if span.get("url"):
        matcher, pattern = "url_prefix", _url_prefix_of(span["url"])
        match_sql, match_params = "substr(url,1,?) = ?", [len(pattern), pattern]
    elif span.get("domain"):
        matcher, pattern = "domain", span["domain"].lower()
        match_sql = "(lower(domain) = ? OR lower(domain) LIKE '%.' || ?)"
        match_params = [pattern, pattern]
    elif span.get("exe"):
        matcher, pattern = "exe", span["exe"]
        match_sql, match_params = "lower(exe) = lower(?)", [pattern]
    else:
        return None

    existing = conn.execute(
        "SELECT id FROM rules WHERE source='learned' AND matcher=? AND pattern=?",
        (matcher, pattern),
    ).fetchone()
    if existing:
        rule_id = existing["id"]
        conn.execute("UPDATE rules SET category_id=?, project_id=? WHERE id=?",
                     (category_id, project_id, rule_id))
        _audit(conn, "rule", rule_id, "retarget", None,
               f"{matcher}:{pattern} -> cat {category_id}")
    else:
        cur = conn.execute(
            "INSERT INTO rules(priority, matcher, pattern, kind_hint, category_id, "
            "project_id, source, created_ts) VALUES(50,?,?,NULL,?,?,'learned',?)",
            (matcher, pattern, category_id, project_id, now_ts()),
        )
        rule_id = int(cur.lastrowid)
        _audit(conn, "rule", rule_id, "create", None,
               f"{matcher}:{pattern} -> cat {category_id}")

    retro = conn.execute(
        f"UPDATE spans SET category_id=?, project_id=?, classified_by='rule', rule_id=? "
        f"WHERE category_id IS NULL AND classified_by IS NULL "
        f"AND kind NOT IN ('idle','locked') AND {match_sql}",
        (category_id, project_id, rule_id, *match_params),
    )
    if rt is not None:
        rt.bump_rules()   # collector reloads its engine on the next tick
    return {"rule_id": rule_id, "matcher": matcher, "pattern": pattern,
            "retro_applied": retro.rowcount}


@router.patch("/spans/{span_id}")
def patch_span(span_id: int, request: Request, body: dict):
    """Popover edit: category / project / free-text label; optional learned rule.
    Every change lands in edits_audit; the span gets edited=1 + classified_by='user'."""
    cfg = request.app.state.cfg
    conn = dbmod.connect()
    try:
        row = _require_span(conn, span_id)
        if row["kind"] in ("idle", "locked") and (
            body.get("category_id") is not None or body.get("project_id") is not None
        ):
            raise HTTPException(status_code=422,
                                detail="idle/locked time cannot be categorized — add a manual block instead")

        new_cat = body["category_id"] if "category_id" in body else row["category_id"]
        new_proj = body["project_id"] if "project_id" in body else row["project_id"]
        if "category_id" in body and "project_id" not in body and new_cat != row["category_id"]:
            new_proj = None   # category change orphans the old project
        _require_category(conn, new_cat)
        _require_project(conn, new_proj, new_cat)

        changed = False
        if new_cat != row["category_id"] or new_proj != row["project_id"]:
            if new_cat != row["category_id"]:
                _audit(conn, "span", span_id, "category_id", row["category_id"], new_cat)
            if new_proj != row["project_id"]:
                _audit(conn, "span", span_id, "project_id", row["project_id"], new_proj)
            conn.execute(
                "UPDATE spans SET category_id=?, project_id=?, classified_by='user', "
                "edited=1 WHERE id=?", (new_cat, new_proj, span_id),
            )
            changed = True
        if "label" in body:
            new_detail = _merge_label(row["detail"], body["label"])
            if new_detail != row["detail"]:
                _audit(conn, "span", span_id, "label", row["detail"], new_detail)
                conn.execute("UPDATE spans SET detail=?, edited=1 WHERE id=?",
                             (new_detail, span_id))
                changed = True

        rule = None
        if body.get("learn_rule") and new_cat is not None:
            rule = _learn_rule(conn, request.app.state.rt, dict(row), new_cat, new_proj)
        if changed or (rule and rule["retro_applied"]):
            goalsmod.invalidate_progress(conn, cfg, row["start_ts"], row["end_ts"])
        out = _span_view(conn, span_id)
    finally:
        conn.close()
    return {"span": out, "rule": rule}


_MANUAL_MAX_S = 86400   # a manual block longer than a day is a typo


@router.post("/spans")
def create_span(request: Request, body: dict):
    """Manual span for offline work (§10.1 "+ Add block"): kind='manual'. MAY
    overlap idle/locked time — reporting subtracts the overlap, re-tagging it."""
    cfg = request.app.state.cfg
    try:
        start_ts, end_ts = int(body["start_ts"]), int(body["end_ts"])
    except (KeyError, ValueError, TypeError):
        raise HTTPException(status_code=422, detail="start_ts and end_ts (epoch seconds) are required")
    if end_ts <= start_ts:
        raise HTTPException(status_code=422, detail="end_ts must be after start_ts")
    if end_ts - start_ts > _MANUAL_MAX_S:
        raise HTTPException(status_code=422, detail="manual span cannot exceed 24h")
    label = str(body.get("label") or "").strip() or None
    conn = dbmod.connect()
    try:
        _require_category(conn, body.get("category_id"))
        _require_project(conn, body.get("project_id"), body.get("category_id"))
        span_id = dbmod.insert_span(conn, {
            "start_ts": start_ts, "end_ts": end_ts, "kind": "manual",
            "exe": None, "app_name": label or "Manual block", "window_title": None,
            "url": None, "domain": None, "detail": {"label": label} if label else None,
            "category_id": body.get("category_id"), "project_id": body.get("project_id"),
            "classified_by": "user" if body.get("category_id") is not None else None,
            "rule_id": None, "ai_confidence": None, "edited": 0,
        })
        _audit(conn, "span", span_id, "create", None,
               f"manual {start_ts}-{end_ts} cat={body.get('category_id')} label={label or ''}")
        goalsmod.invalidate_progress(conn, cfg, start_ts, end_ts)
        out = _span_view(conn, span_id)
    finally:
        conn.close()
    return {"span": out}


@router.delete("/spans/{span_id}")
def delete_span(span_id: int, request: Request):
    cfg = request.app.state.cfg
    conn = dbmod.connect()
    try:
        row = _require_span(conn, span_id)
        _audit(conn, "span", span_id, "delete",
               f"{row['kind']} {row['start_ts']}-{row['end_ts']} cat={row['category_id']}", None)
        conn.execute("DELETE FROM spans WHERE id=?", (span_id,))
        goalsmod.invalidate_progress(conn, cfg, row["start_ts"], row["end_ts"])
    finally:
        conn.close()
    return {"deleted": True, "id": span_id}


@router.post("/spans/{span_id}/split")
def split_span(span_id: int, request: Request, body: dict):
    """Split a span at ``at_ts`` (strictly inside): the original keeps the head,
    a copy takes the tail. Both halves get edited=1 so the UI shows the touch."""
    try:
        at_ts = int(body["at_ts"])
    except (KeyError, ValueError, TypeError):
        raise HTTPException(status_code=422, detail="at_ts (epoch seconds) is required")
    conn = dbmod.connect()
    try:
        row = _require_span(conn, span_id)
        if not (row["start_ts"] < at_ts < row["end_ts"]):
            raise HTTPException(status_code=422, detail="at_ts must fall strictly inside the span")
        _audit(conn, "span", span_id, "split",
               f"{row['start_ts']}-{row['end_ts']}", f"at {at_ts}")
        conn.execute("UPDATE spans SET end_ts=?, edited=1 WHERE id=?", (at_ts, span_id))
        tail = {c: row[c] for c in dbmod._SPAN_COLS}
        tail.update({"start_ts": at_ts, "end_ts": row["end_ts"], "edited": 1})
        tail_id = dbmod.insert_span(conn, tail)
        out = [_span_view(conn, span_id), _span_view(conn, tail_id)]
    finally:
        conn.close()
    return {"spans": out}


# --- review queue (§10.5; Phase 7) ---------------------------------------------
_REVIEW_CONF = 0.8   # AI classifications below this need human eyes (§8.3)


@router.get("/review")
def get_review(days: int = 30):
    """Uncategorized + low-confidence spans grouped by identity (domain/exe/app),
    largest total time first."""
    days = max(1, min(days, 365))
    cutoff = now_ts() - days * 86400
    conn = dbmod.connect()
    try:
        rows = conn.execute(
            "SELECT id, start_ts, end_ts, duration_s, kind, exe, app_name, "
            "window_title, domain, detail, category_id, classified_by, ai_confidence "
            "FROM spans WHERE start_ts >= ? AND kind NOT IN ('idle','locked','manual') "
            "AND (category_id IS NULL OR (classified_by='ai' AND ai_confidence < ?)) "
            "ORDER BY start_ts DESC",
            (cutoff, _REVIEW_CONF),
        ).fetchall()
    finally:
        conn.close()
    groups: dict[str, dict] = {}
    for r in rows:
        key = r["domain"] or r["exe"] or r["app_name"] or "unknown"
        g = groups.setdefault(key, {
            "key": key, "domain": r["domain"], "exe": r["exe"], "app_name": r["app_name"],
            "count": 0, "total_s": 0, "span_ids": [], "sample_titles": [], "last_ts": 0,
        })
        g["count"] += 1
        g["total_s"] += r["duration_s"]
        g["span_ids"].append(r["id"])
        g["last_ts"] = max(g["last_ts"], r["end_ts"])
        title = r["window_title"]
        if title and title not in g["sample_titles"] and len(g["sample_titles"]) < 3:
            g["sample_titles"].append(title)
    out = sorted(groups.values(), key=lambda g: -g["total_s"])
    return {"days": days, "total_spans": len(rows), "groups": out}


_ASSIGN_MAX = 1000


@router.post("/review/assign")
def review_assign(request: Request, body: dict):
    """Bulk assign a category (+ optional project / learned rule) to spans."""
    cfg = request.app.state.cfg
    span_ids = body.get("span_ids")
    if not isinstance(span_ids, list) or not span_ids or len(span_ids) > _ASSIGN_MAX:
        raise HTTPException(status_code=422, detail=f"span_ids must be a list of 1..{_ASSIGN_MAX} ids")
    try:
        span_ids = [int(i) for i in span_ids]
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="span_ids must be integers")
    conn = dbmod.connect()
    try:
        _require_category(conn, body.get("category_id"), required=True)
        _require_project(conn, body.get("project_id"), body.get("category_id"))
        cat, proj = body["category_id"], body.get("project_id")
        ph = ",".join("?" for _ in span_ids)
        rows = conn.execute(
            f"SELECT * FROM spans WHERE id IN ({ph}) AND kind NOT IN ('idle','locked')",
            span_ids,
        ).fetchall()
        if not rows:
            raise HTTPException(status_code=404, detail="no matching spans")
        lo = min(r["start_ts"] for r in rows)
        hi = max(r["end_ts"] for r in rows)
        for r in rows:
            if r["category_id"] != cat:
                _audit(conn, "span", r["id"], "category_id", r["category_id"], cat)
        ids = [r["id"] for r in rows]
        ph = ",".join("?" for _ in ids)
        conn.execute(
            f"UPDATE spans SET category_id=?, project_id=?, classified_by='user', "
            f"edited=1 WHERE id IN ({ph})", (cat, proj, *ids),
        )
        rules = []
        if body.get("learn_rule"):
            # one rule per distinct identity — a bulk assign can span several
            # groups (notion.so + substack.com), each deserves its own rule
            seen: set[tuple] = set()
            for r in rows:
                ident = (("url_prefix", _url_prefix_of(r["url"])) if r["url"]
                         else ("domain", r["domain"].lower()) if r["domain"]
                         else ("exe", r["exe"].lower()) if r["exe"] else None)
                if ident is None or ident in seen:
                    continue
                seen.add(ident)
                learned = _learn_rule(conn, request.app.state.rt, dict(r), cat, proj)
                if learned:
                    rules.append(learned)
        goalsmod.invalidate_progress(conn, cfg, lo, hi)
    finally:
        conn.close()
    return {"updated": len(ids), "rules": rules}


# --- goals (§10.4, §10.7; Phase 8) ----------------------------------------------
def _goal_or_404(conn, goal_id: int):
    row = conn.execute("SELECT * FROM goals WHERE id=?", (goal_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="goal not found")
    return row


def _validate_goal(conn, g: dict) -> dict:
    """Validate a complete goal dict (create, or existing row merged with a patch)."""
    name = str(g.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="name is required")
    if g.get("period") not in goalsmod.PERIODS:
        raise HTTPException(status_code=422, detail=f"period must be one of {goalsmod.PERIODS}")
    if g.get("direction") not in goalsmod.DIRECTIONS:
        raise HTTPException(status_code=422, detail=f"direction must be one of {goalsmod.DIRECTIONS}")
    try:
        target = int(g["target_minutes"])
    except (KeyError, ValueError, TypeError):
        raise HTTPException(status_code=422, detail="target_minutes (int) is required")
    if target < 0:
        raise HTTPException(status_code=422, detail="target_minutes must be >= 0")
    cat, proj = g.get("category_id"), g.get("project_id")
    if (cat is None) == (proj is None):
        raise HTTPException(status_code=422, detail="exactly one of category_id / project_id is required")
    _require_category(conn, cat)
    _require_project(conn, proj)
    days = g.get("active_days")
    if days is not None:
        if g["period"] != "daily":
            raise HTTPException(status_code=422, detail="active_days applies to daily goals only")
        if (not isinstance(days, list) or not days
                or any(not isinstance(d, int) or d < 0 or d > 6 for d in days)):
            raise HTTPException(status_code=422, detail="active_days must be a non-empty list of 0..6 (Mon=0)")
        days = sorted(set(days))
    return {"name": name, "period": g["period"], "direction": g["direction"],
            "target_minutes": target, "category_id": cat, "project_id": proj,
            "active_days": json.dumps(days) if days else None}


@router.get("/goals")
def list_goals(request: Request, include_archived: bool = False):
    """Goal cards (§10.4): progress, streaks, per-period history."""
    cfg = request.app.state.cfg
    conn = dbmod.connect()
    try:
        where = "" if include_archived else "WHERE archived=0"
        rows = conn.execute(f"SELECT * FROM goals {where} ORDER BY id").fetchall()
        cards = [goalsmod.goal_card(conn, cfg, dict(r)) for r in rows]
    finally:
        conn.close()
    return {"goals": cards}


@router.post("/goals")
def create_goal(request: Request, body: dict):
    cfg = request.app.state.cfg
    conn = dbmod.connect()
    try:
        g = _validate_goal(conn, body)
        cur = conn.execute(
            "INSERT INTO goals(name, period, direction, target_minutes, category_id, "
            "project_id, active_days, created_ts) VALUES(?,?,?,?,?,?,?,?)",
            (g["name"], g["period"], g["direction"], g["target_minutes"],
             g["category_id"], g["project_id"], g["active_days"], now_ts()),
        )
        goal_id = int(cur.lastrowid)
        _audit(conn, "goal", goal_id, "create", None,
               f"{g['name']} {g['direction']} {g['target_minutes']}m {g['period']}")
        card = goalsmod.goal_card(conn, cfg, dict(_goal_or_404(conn, goal_id)))
    finally:
        conn.close()
    return {"goal": card}


@router.patch("/goals/{goal_id}")
def update_goal(goal_id: int, request: Request, body: dict):
    cfg = request.app.state.cfg
    _EDITABLE = ("name", "period", "direction", "target_minutes",
                 "category_id", "project_id", "active_days")
    conn = dbmod.connect()
    try:
        row = _goal_or_404(conn, goal_id)
        merged = dict(row)
        raw_days = row["active_days"]
        merged["active_days"] = json.loads(raw_days) if raw_days else None
        if "category_id" in body and body["category_id"] is not None and "project_id" not in body:
            merged["project_id"] = None   # switching target: category now owns the goal
        if "project_id" in body and body["project_id"] is not None and "category_id" not in body:
            merged["category_id"] = None
        for f in _EDITABLE:
            if f in body:
                merged[f] = body[f]
        if merged.get("period") != "daily":
            merged["active_days"] = merged["active_days"] if "active_days" in body else None
        g = _validate_goal(conn, merged)
        for f in _EDITABLE:
            old = row[f]
            new = g[f]
            if str(old) != str(new):
                _audit(conn, "goal", goal_id, f, old, new)
        conn.execute(
            "UPDATE goals SET name=?, period=?, direction=?, target_minutes=?, "
            "category_id=?, project_id=?, active_days=? WHERE id=?",
            (g["name"], g["period"], g["direction"], g["target_minutes"],
             g["category_id"], g["project_id"], g["active_days"], goal_id),
        )
        # target/direction/period changes invalidate every cached verdict
        conn.execute("DELETE FROM goal_progress WHERE goal_id=?", (goal_id,))
        card = goalsmod.goal_card(conn, cfg, dict(_goal_or_404(conn, goal_id)))
    finally:
        conn.close()
    return {"goal": card}


@router.delete("/goals/{goal_id}")
def archive_goal(goal_id: int):
    """Archive, never hard-delete — history (goal_progress) stays queryable."""
    conn = dbmod.connect()
    try:
        _goal_or_404(conn, goal_id)
        _audit(conn, "goal", goal_id, "archived", 0, 1)
        conn.execute("UPDATE goals SET archived=1 WHERE id=?", (goal_id,))
    finally:
        conn.close()
    return {"archived": True, "id": goal_id}


@router.get("/goals/progress")
def goals_progress(request: Request, period: str = "daily", date: str | None = None):
    """Progress of all goals of a period type for the period containing ``date``."""
    cfg = request.app.state.cfg
    if period not in goalsmod.PERIODS:
        raise HTTPException(status_code=422, detail=f"period must be one of {goalsmod.PERIODS}")
    d = _parse_date(date, "date") if date else _today(cfg)
    pstart = goalsmod.period_start_of(d, period)
    conn = dbmod.connect()
    try:
        rows = conn.execute(
            "SELECT * FROM goals WHERE archived=0 AND period=? ORDER BY id", (period,)
        ).fetchall()
        out = []
        for r in rows:
            goal = dict(r)
            ev = goalsmod.evaluate(conn, cfg, goal, pstart)
            out.append({
                "goal_id": goal["id"], "name": goal["name"], "direction": goal["direction"],
                "target_minutes": goal["target_minutes"], "category_id": goal["category_id"],
                "project_id": goal["project_id"], "period_start": ev["period_start"],
                "minutes": ev["minutes"], "met": ev["met"],
            })
    finally:
        conn.close()
    return {"period": period, "date": d, "period_start": pstart, "goals": out}


# --- daily journal (§10.1, §10.7) --------------------------------------------
@router.get("/summary/{date}")
def get_summary(date: str, request: Request):
    conn = dbmod.connect()
    try:
        row = conn.execute("SELECT * FROM day_summaries WHERE date=?", (date,)).fetchone()
    finally:
        conn.close()
    return _summary_dict(row) if row else {"date": date, "exists": False}


@router.patch("/summary/{date}")
def patch_summary(date: str, request: Request, body: dict):
    conn = dbmod.connect()
    try:
        row = conn.execute("SELECT * FROM day_summaries WHERE date=?", (date,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="no summary for that date")
        for field in ("narrative_md", "user_note_md"):
            if field in body:
                _audit(conn, "summary", date, field, row[field], body[field])
                conn.execute(f"UPDATE day_summaries SET {field}=?, edited=1 WHERE date=?",
                             (body[field], date))
        if "highlights" in body:
            _audit(conn, "summary", date, "highlights", row["highlights"],
                   json.dumps(body["highlights"]))
            conn.execute("UPDATE day_summaries SET highlights=?, edited=1 WHERE date=?",
                         (json.dumps(body["highlights"]), date))
        row = conn.execute("SELECT * FROM day_summaries WHERE date=?", (date,)).fetchone()
    finally:
        conn.close()
    return _summary_dict(row)


@router.post("/summary/{date}/generate")
def generate_summary(date: str, request: Request):
    cfg = request.app.state.cfg
    conn = dbmod.connect()
    try:
        res = jobs.summarize_day(conn, GroqClient(cfg), cfg, date, force=True)
        row = conn.execute("SELECT * FROM day_summaries WHERE date=?", (date,)).fetchone()
    except GroqError as e:
        raise HTTPException(status_code=503, detail=f"AI unavailable: {e}")
    finally:
        conn.close()
    return {"status": res["status"], **_summary_dict(row)}


# --- time leaks (§10.3, deterministic) ----------------------------------------
@router.get("/insights/leaks")
def get_leaks(request: Request, week: str | None = None):
    cfg = request.app.state.cfg
    ws = reporting.week_start_of(_parse_date(week, "week") if week else _today(cfg))
    conn = dbmod.connect()
    try:
        leaks = reporting.time_leaks(conn, cfg, ws)
    finally:
        conn.close()
    return {"week_start": ws, "leaks": leaks}


# --- weekly insight (§10.3, §10.7) -------------------------------------------
@router.get("/insights/weekly")
def get_weekly(request: Request, week: str | None = None):
    cfg = request.app.state.cfg
    ws = reporting.week_start_of(week or _today(cfg))
    conn = dbmod.connect()
    try:
        raw = dbmod.get_setting(conn, f"weekly_{ws}", None)
    finally:
        conn.close()
    if not raw:
        return {"week_start": ws, "exists": False}
    return {"exists": True, **json.loads(raw)}


@router.post("/insights/weekly/generate")
def generate_weekly(request: Request, body: dict | None = None):
    cfg = request.app.state.cfg
    ws = reporting.week_start_of((body or {}).get("week") or _today(cfg))
    conn = dbmod.connect()
    try:
        record = jobs.weekly_insight(conn, GroqClient(cfg), cfg, ws, force=True)
    except GroqError as e:
        raise HTTPException(status_code=503, detail=f"AI unavailable: {e}")
    finally:
        conn.close()
    return {"exists": True, **record}
