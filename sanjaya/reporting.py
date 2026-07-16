"""Deterministic reporting (PRD §8.6, §9.3 B/C, §13.8). Turns raw spans into the
compressed day/week payloads the journal and weekly-insight prompts consume — and
computes the focus score — WITHOUT any AI. Pure over (conn, cfg): fully testable.

Midnight-spanning spans are clipped to the local day at query time (§13.8), so a
span that straddles the day boundary contributes only its in-day seconds.
"""
from __future__ import annotations

import json

from . import focus
from . import goals as goals_engine
from .db import get_setting
from .timeutil import day_bounds, local_dt, now_ts

_INACTIVE = ("idle", "locked")
_TITLE_KEYS = ("video_title", "topic", "query", "file", "page_title", "folder")
_MAX_TIMELINE_LINES = 40
_IDLE_LINE_MIN_S = 300      # only surface idle gaps >= 5 min in the timeline


# --- small formatters --------------------------------------------------------
def fmt_hm(seconds: int) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 3600}h {seconds % 3600 // 60:02d}m"


def fmt_hmm(seconds: int) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}"


def _clip(a: int, b: int, lo: int, hi: int) -> int:
    return max(0, min(b, hi) - max(a, lo))


def _merge_intervals(ivals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Union of half-open intervals, sorted and merged."""
    out: list[tuple[int, int]] = []
    for a, b in sorted(ivals):
        if b <= a:
            continue
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _overlap_with(a: int, b: int, merged: list[tuple[int, int]]) -> int:
    """Seconds of [a,b) covered by a merged interval union."""
    return sum(_clip(a, b, lo, hi) for lo, hi in merged)


def _manual_intervals(spans, lo: int, hi: int) -> list[tuple[int, int]]:
    """Merged manual-span intervals clipped to the day. Manual spans MAY overlap
    idle/locked time and re-tag it (§10.1) — reporting subtracts this overlap
    from idle/locked durations so tracked + idle + locked never exceeds 24h."""
    return _merge_intervals([
        (max(s["start_ts"], lo), min(s["end_ts"], hi))
        for s in spans if s["kind"] == "manual"
    ])


def _detail(span) -> dict:
    d = span.get("detail")
    if not d:
        return {}
    try:
        return json.loads(d) if isinstance(d, str) else dict(d)
    except (ValueError, TypeError):
        return {}


def _title_of(span) -> str | None:
    d = _detail(span)
    if d.get("video_title"):  # include the channel so the journal can cite it honestly
        vt = str(d["video_title"])
        return f"{vt} ({d['channel']})" if d.get("channel") else vt
    for k in _TITLE_KEYS:
        if d.get(k):
            return str(d[k])
    return span.get("window_title") or None


def _label_of(span) -> str | None:
    return span.get("domain") or span.get("app_name") or span.get("exe")


# --- day data ----------------------------------------------------------------
def _day_spans(conn, lo: int, hi: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM spans WHERE start_ts < ? AND end_ts > ? ORDER BY start_ts",
        (hi, lo),
    ).fetchall()
    return [dict(r) for r in rows]


def _category_map(conn) -> dict[int, dict]:
    return {r["id"]: {"name": r["name"], "is_productive": r["is_productive"]}
            for r in conn.execute("SELECT id, name, is_productive FROM categories")}


def _timeline(spans, cats, tz, lo, hi) -> str:
    def hhmm(ts: int) -> str:
        return local_dt(max(lo, min(ts, hi)), tz).strftime("%H:%M")

    lines: list[str] = []
    block: dict | None = None

    def flush():
        nonlocal block
        if block is None:
            return
        cat = "Uncategorized" if block["cat"] is None else cats.get(block["cat"], {}).get("name", "Uncategorized")
        titles = []
        for t in block["titles"]:
            if t and t not in titles:
                titles.append(t)
        label = block["label"] or ""
        tail = (" — " + "; ".join(titles[:3])) if titles else ""
        lines.append(f"{hhmm(block['start'])}–{hhmm(block['end'])}  {cat}  {label}{tail}")
        block = None

    for s in spans:
        dur = _clip(s["start_ts"], s["end_ts"], lo, hi)
        if dur <= 0:
            continue
        if s["kind"] in _INACTIVE:
            flush()
            if s["kind"] == "idle" and dur >= _IDLE_LINE_MIN_S:
                lines.append(f"{hhmm(s['start_ts'])}–{hhmm(s['end_ts'])}  (idle {fmt_hm(dur)})")
            elif s["kind"] == "locked" and dur >= _IDLE_LINE_MIN_S:
                lines.append(f"{hhmm(s['start_ts'])}–{hhmm(s['end_ts'])}  (locked {fmt_hm(dur)})")
            continue
        if block is not None and block["cat"] == s["category_id"]:
            block["end"] = max(block["end"], min(s["end_ts"], hi))
            block["titles"].append(_title_of(s))
        else:
            flush()
            block = {"cat": s["category_id"], "start": max(s["start_ts"], lo),
                     "end": min(s["end_ts"], hi), "label": _label_of(s),
                     "titles": [_title_of(s)]}
    flush()

    if len(lines) > _MAX_TIMELINE_LINES:
        dropped = len(lines) - _MAX_TIMELINE_LINES
        lines = lines[:_MAX_TIMELINE_LINES] + [f"... (+{dropped} more blocks)"]
    return "\n".join(lines) if lines else "(no tracked activity)"


def daily_goals(conn, cfg, date: str) -> list[dict]:
    """Structured status of active daily goals for a day — delegated to the
    goals engine (Phase 8): clipped span sums, streak-as-of-date, active_days."""
    return goals_engine.goals_for_day(conn, cfg, date)


def _goal_status(goals: list[dict]) -> str:
    if not goals:
        return "none"
    return ", ".join(
        f"{g['name']}: {'met' if g['met'] else 'missed'} ({g['minutes']}m vs {g['target_minutes']}m)"
        for g in goals
    )


def _stopwatch(conn, lo: int, hi: int) -> str:
    rows = conn.execute(
        "SELECT label, last_value_s FROM stopwatch_readings WHERE ts >= ? AND ts < ? ORDER BY ts",
        (lo, hi),
    ).fetchall()
    if not rows:
        return "none"
    return ", ".join(f"{r['label'] or 'timer'}: {fmt_hmm(r['last_value_s'])}" for r in rows)


def _edits(conn, lo: int, hi: int) -> str:
    rows = conn.execute(
        "SELECT field, new_value FROM edits_audit WHERE entity='span' AND ts >= ? AND ts < ? "
        "ORDER BY ts", (lo, hi),
    ).fetchall()
    if not rows:
        return "none"
    return ", ".join(f"{r['field']}->{r['new_value']}" for r in rows[:20])


def _yesterday_suggestions(conn, prev_date: str) -> str:
    row = conn.execute(
        "SELECT suggestions FROM day_summaries WHERE date=?", (prev_date,)
    ).fetchone()
    if not row or not row["suggestions"]:
        return "none"
    try:
        items = json.loads(row["suggestions"])
    except (ValueError, TypeError):
        return "none"
    return "; ".join(items) if items else "none"


def _prev_date(date: str) -> str:
    from datetime import datetime, timedelta
    return (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")


def build_day_payload(conn, cfg, date: str) -> dict:
    """Assemble the compressed day payload (§9.3 B) + deterministic focus score."""
    tz, dsh = cfg.timezone, cfg.day_start_hour
    lo, hi = day_bounds(date, tz, dsh)
    spans = _day_spans(conn, lo, hi)
    cats = _category_map(conn)

    active_s = idle_s = 0
    cat_secs: dict = {}
    focus_spans: list[dict] = []
    manual_iv = _manual_intervals(spans, lo, hi)
    for s in spans:
        dur = _clip(s["start_ts"], s["end_ts"], lo, hi)
        if dur <= 0:
            continue
        if s["kind"] in _INACTIVE:
            # subtract time re-tagged by an overlapping manual span (§10.1)
            dur -= _overlap_with(max(s["start_ts"], lo), min(s["end_ts"], hi), manual_iv)
            if s["kind"] == "idle":
                idle_s += max(0, dur)
            fs_kind = s["kind"]
            is_prod = 0
        else:
            active_s += dur
            cid = s["category_id"]
            cat_secs[cid] = cat_secs.get(cid, 0) + dur
            fs_kind = s["kind"]
            is_prod = cats.get(cid, {}).get("is_productive", 0) if cid is not None else 0
        focus_spans.append({
            "kind": fs_kind, "start_ts": max(s["start_ts"], lo), "end_ts": min(s["end_ts"], hi),
            "exe": s["exe"], "project_id": s["project_id"], "is_productive": is_prod,
        })

    comp = focus.components(focus_spans, focus.params_from_config(cfg))

    totals_map = {("uncategorized" if k is None else str(k)): v for k, v in cat_secs.items()}
    totals_str = ", ".join(
        f"{('Uncategorized' if k is None else cats.get(k, {}).get('name', 'Uncategorized'))}: {fmt_hmm(v)}"
        for k, v in sorted(cat_secs.items(), key=lambda kv: -kv[1])
    ) or "none"

    goals = daily_goals(conn, cfg, date)

    return {
        "date": date,
        "weekday": local_dt(lo, tz).strftime("%A"),
        "active_seconds": active_s,
        "idle_seconds": idle_s,
        "active_h": active_s // 3600,
        "active_m": active_s % 3600 // 60,
        "idle_time": fmt_hm(idle_s),
        "focus_score": comp["score"],
        "focus_components": comp,
        "category_totals_map": totals_map,
        "category_totals": totals_str,
        "goals": goals,
        "goal_status": _goal_status(goals),
        "timeline": _timeline(spans, cats, tz, lo, hi),
        "stopwatch": _stopwatch(conn, lo, hi),
        "edits": _edits(conn, lo, hi),
        "yesterday_suggestions": _yesterday_suggestions(conn, _prev_date(date)),
        "has_activity": active_s > 0,
    }


def day_totals(conn, cfg, date: str) -> dict:
    """Lean per-day aggregate for range charts (History/Insights): active/idle
    seconds + category seconds, no timeline/goals/prompt strings. Focus score
    prefers the stored day_summaries value; computes deterministically otherwise."""
    tz, dsh = cfg.timezone, cfg.day_start_hour
    lo, hi = day_bounds(date, tz, dsh)
    spans = _day_spans(conn, lo, hi)
    cats = _category_map(conn)

    active_s = idle_s = 0
    cat_secs: dict = {}
    focus_spans: list[dict] = []
    manual_iv = _manual_intervals(spans, lo, hi)
    for s in spans:
        dur = _clip(s["start_ts"], s["end_ts"], lo, hi)
        if dur <= 0:
            continue
        if s["kind"] in _INACTIVE:
            dur -= _overlap_with(max(s["start_ts"], lo), min(s["end_ts"], hi), manual_iv)
            if s["kind"] == "idle":
                idle_s += max(0, dur)
            is_prod = 0
        else:
            active_s += dur
            cid = s["category_id"]
            cat_secs[cid] = cat_secs.get(cid, 0) + dur
            is_prod = cats.get(cid, {}).get("is_productive", 0) if cid is not None else 0
        focus_spans.append({
            "kind": s["kind"], "start_ts": max(s["start_ts"], lo), "end_ts": min(s["end_ts"], hi),
            "exe": s["exe"], "project_id": s["project_id"], "is_productive": is_prod,
        })

    stored = conn.execute(
        "SELECT focus_score FROM day_summaries WHERE date=?", (date,)
    ).fetchone()
    if stored is not None and stored["focus_score"] is not None:
        score = stored["focus_score"]
    elif active_s > 0:
        score = focus.components(focus_spans, focus.params_from_config(cfg))["score"]
    else:
        score = None

    return {
        "date": date,
        "active_seconds": active_s,
        "idle_seconds": idle_s,
        "focus_score": score,
        "category_totals": {("uncategorized" if k is None else str(k)): v
                            for k, v in cat_secs.items()},
    }


def build_range(conn, cfg, date_from: str, date_to: str) -> list[dict]:
    """Inclusive per-day aggregates for ``/api/range`` (§10.7)."""
    from datetime import datetime, timedelta
    d0 = datetime.strptime(date_from, "%Y-%m-%d")
    d1 = datetime.strptime(date_to, "%Y-%m-%d")
    out = []
    while d0 <= d1:
        out.append(day_totals(conn, cfg, d0.strftime("%Y-%m-%d")))
        d0 += timedelta(days=1)
    return out


def time_leaks(conn, cfg, week_start: str, top_n: int = 10) -> list[dict]:
    """Top leak domains by week-over-week Δ (§10.3): time on domains whose span
    is uncategorized or in a non-productive category, this week vs the previous
    week. Deterministic — no AI."""
    from datetime import datetime, timedelta
    tz, dsh = cfg.timezone, cfg.day_start_hour
    d0 = datetime.strptime(week_start, "%Y-%m-%d")
    this_lo = day_bounds(week_start, tz, dsh)[0]
    this_hi = day_bounds((d0 + timedelta(days=6)).strftime("%Y-%m-%d"), tz, dsh)[1]
    prev_lo = day_bounds((d0 - timedelta(days=7)).strftime("%Y-%m-%d"), tz, dsh)[0]

    def _bucket(lo: int, hi: int) -> dict[str, int]:
        rows = conn.execute(
            "SELECT s.domain, s.start_ts, s.end_ts FROM spans s "
            "LEFT JOIN categories c ON c.id = s.category_id "
            "WHERE s.domain IS NOT NULL AND s.start_ts < ? AND s.end_ts > ? "
            "AND s.kind NOT IN ('idle','locked') "
            "AND (s.category_id IS NULL OR c.is_productive = 0)",
            (hi, lo),
        ).fetchall()
        out: dict[str, int] = {}
        for r in rows:
            dur = _clip(r["start_ts"], r["end_ts"], lo, hi)
            if dur > 0:
                out[r["domain"]] = out.get(r["domain"], 0) + dur
        return out

    cur, prev = _bucket(this_lo, this_hi), _bucket(prev_lo, this_lo)
    leaks = [
        {"domain": d, "this_s": cur.get(d, 0), "prev_s": prev.get(d, 0),
         "delta_s": cur.get(d, 0) - prev.get(d, 0)}
        for d in set(cur) | set(prev)
    ]
    leaks.sort(key=lambda x: (-x["delta_s"], -x["this_s"]))
    return leaks[:top_n]


# --- week data ---------------------------------------------------------------
def week_start_of(date: str) -> str:
    """Monday (ISO) of the week containing ``date``."""
    from datetime import datetime, timedelta
    d = datetime.strptime(date, "%Y-%m-%d")
    return (d - timedelta(days=d.weekday())).strftime("%Y-%m-%d")


def _week_dates(week_start: str) -> list[str]:
    from datetime import datetime, timedelta
    d0 = datetime.strptime(week_start, "%Y-%m-%d")
    return [(d0 + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]


def build_week_payload(conn, cfg, week_start: str) -> dict:
    dates = _week_dates(week_start)
    cats = _category_map(conn)
    totals: dict = {}
    focus_scores: list[str] = []
    day_lines: list[str] = []
    for d in dates:
        row = conn.execute(
            "SELECT focus_score, category_totals, narrative_md FROM day_summaries WHERE date=?",
            (d,),
        ).fetchone()
        if not row:
            focus_scores.append(f"{d}: -")
            continue
        focus_scores.append(f"{d}: {row['focus_score'] if row['focus_score'] is not None else '-'}")
        if row["category_totals"]:
            try:
                for k, v in json.loads(row["category_totals"]).items():
                    totals[k] = totals.get(k, 0) + int(v)
            except (ValueError, TypeError):
                pass
        if row["narrative_md"]:
            day_lines.append(f"{d}: {row['narrative_md'][:220].strip()}")

    def name_of(key: str) -> str:
        if key == "uncategorized":
            return "Uncategorized"
        try:
            return cats.get(int(key), {}).get("name", key)
        except ValueError:
            return key

    totals_str = ", ".join(
        f"{name_of(k)}: {fmt_hmm(v)}" for k, v in sorted(totals.items(), key=lambda kv: -kv[1])
    ) or "none"

    return {
        "week_start": week_start,
        "week_end": dates[-1],
        "category_totals": totals_str,
        "goal_streaks": goals_engine.week_goal_streaks(conn, cfg, week_start),
        "focus_scores": ", ".join(focus_scores),
        "day_summaries": "\n".join(day_lines) if day_lines else "(no daily summaries yet)",
    }


# --- honesty heuristic (used by prompt-regression tests, §15) ----------------
import re as _re

_PROPER = _re.compile(r"\b([A-Z][A-Za-z0-9][A-Za-z0-9.+&_-]*)\b")
_STOPWORDS = {
    "You", "Your", "The", "This", "That", "Today", "Tonight", "Sanjaya", "It", "A", "An",
    "I", "We", "At", "In", "On", "Of", "And", "But", "So", "For", "To", "With", "You'll",
    "You've", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "Focus", "Active", "Idle", "Category", "Goal", "Overall", "Nice", "Great", "Keep",
    "AI", "YouTube", "Uncategorized",   # generic product/system terms, not activities
}


def proper_nouns(text: str) -> set[str]:
    return {m.group(1) for m in _PROPER.finditer(text or "")} - _STOPWORDS


def hallucinated_nouns(narrative: str, payload_text: str) -> set[str]:
    """Proper nouns in the narrative absent from the source payload (§15)."""
    haystack = payload_text or ""
    return {n for n in proper_nouns(narrative) if n not in haystack}
