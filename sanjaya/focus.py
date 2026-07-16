"""Deterministic focus score (PRD §8.6). Pure and unit-tested — never AI.

    focus_score = 100 * (w_P*P + w_D*D + w_S*S)
      P = productive_seconds / active_seconds
      D = min(1, longest_deep_block_minutes / target)   (deep block = >= min minutes
          continuous same project, interruptions < interruption_max)
      S = 1 - min(1, context_switches_per_hour / norm)  (switch = boundary between
          different exes, ignoring sub-flicker spans)

Each span is a dict with: kind, start_ts, end_ts, exe, project_id, is_productive.
Weights/thresholds come from ``config.toml [focus]`` so they are tunable.
"""
from __future__ import annotations

from typing import Iterable

DEFAULTS = {
    "w_productive": 0.5,
    "w_deep": 0.3,
    "w_switch": 0.2,
    "deep_block_min_minutes": 25,
    "deep_block_target_minutes": 90,
    "deep_interruption_max_s": 120,
    "switch_flicker_s": 10,
    "switch_norm_per_hour": 30,
}

_INACTIVE = {"idle", "locked"}


def _dur(s: dict) -> int:
    return int(s["end_ts"]) - int(s["start_ts"])


def _longest_deep_block(active: list[dict], min_s: int, gap_max_s: int) -> int:
    """Longest same-project cluster (seconds) whose wall length >= min_s.

    Spans of the same project are clustered along the timeline; a gap shorter
    than ``gap_max_s`` between two same-project spans is a tolerated interruption
    and keeps the block open. Returns 0 if no cluster qualifies.
    """
    by_proj: dict[int, list[dict]] = {}
    for s in active:
        pid = s.get("project_id")
        if pid is not None:
            by_proj.setdefault(pid, []).append(s)

    best = 0
    for spans in by_proj.values():
        spans.sort(key=lambda s: s["start_ts"])
        cl_start = spans[0]["start_ts"]
        cl_end = spans[0]["end_ts"]
        for s in spans[1:]:
            if s["start_ts"] - cl_end < gap_max_s:
                cl_end = max(cl_end, s["end_ts"])
            else:
                best = max(best, cl_end - cl_start)
                cl_start, cl_end = s["start_ts"], s["end_ts"]
        best = max(best, cl_end - cl_start)

    return best if best >= min_s else 0


def _context_switches(active: list[dict], flicker_s: int) -> int:
    """Count exe boundaries, ignoring sub-flicker spans."""
    seq = [s for s in active if s.get("exe") and _dur(s) >= flicker_s]
    seq.sort(key=lambda s: s["start_ts"])
    return sum(1 for a, b in zip(seq, seq[1:]) if a["exe"] != b["exe"])


def components(spans: Iterable[dict], params: dict | None = None) -> dict:
    p = {**DEFAULTS, **(params or {})}
    active = [s for s in spans if s.get("kind") not in _INACTIVE]

    active_s = sum(_dur(s) for s in active)
    if active_s <= 0:
        return {"P": 0.0, "D": 0.0, "S": 0.0, "score": 0.0,
                "active_s": 0, "productive_s": 0, "switches": 0,
                "longest_deep_s": 0}

    productive_s = sum(_dur(s) for s in active if s.get("is_productive"))
    P = productive_s / active_s

    longest_deep_s = _longest_deep_block(
        active, p["deep_block_min_minutes"] * 60, p["deep_interruption_max_s"]
    )
    D = min(1.0, (longest_deep_s / 60) / p["deep_block_target_minutes"])

    switches = _context_switches(active, p["switch_flicker_s"])
    switches_per_hour = switches / (active_s / 3600)
    S = 1 - min(1.0, switches_per_hour / p["switch_norm_per_hour"])

    score = 100 * (p["w_productive"] * P + p["w_deep"] * D + p["w_switch"] * S)
    return {"P": P, "D": D, "S": S, "score": round(score, 1),
            "active_s": active_s, "productive_s": productive_s,
            "switches": switches, "longest_deep_s": longest_deep_s}


def score(spans: Iterable[dict], params: dict | None = None) -> float:
    return components(spans, params)["score"]


def params_from_config(cfg) -> dict:
    """Extract the [focus] section from a Config into a plain params dict."""
    section = cfg.section("focus") if hasattr(cfg, "section") else dict(cfg)
    return {**DEFAULTS, **section}
