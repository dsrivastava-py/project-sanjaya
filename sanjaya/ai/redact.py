"""Outbound-payload redaction (PRD §9.2). Every string that leaves the machine
passes through here: the user's ``settings.redaction_patterns`` regex list is
applied, and the (already derived) payload is dumped to disk for audit when
``debug_ai_payloads`` is on. The payload BUILDERS are responsible for sending
derived text only (domains not full URLs, file names not paths) — this module is
the second line of defence plus the user's own regexes.
"""
from __future__ import annotations

import json
import re

from .. import paths
from ..log import get

_log = get("ai.redact")
_MASK = "[redacted]"


def compile_patterns(patterns: list[str] | None) -> list[re.Pattern]:
    out: list[re.Pattern] = []
    for p in patterns or []:
        try:
            out.append(re.compile(p))
        except re.error:
            _log.warning("skipping invalid redaction pattern: %r", p)
    return out


def redact_text(text: str, compiled: list[re.Pattern]) -> str:
    if not text:
        return text
    for rx in compiled:
        text = rx.sub(_MASK, text)
    return text


def redact_obj(obj, compiled: list[re.Pattern]):
    """Recursively redact all strings inside dict/list/str structures."""
    if isinstance(obj, str):
        return redact_text(obj, compiled)
    if isinstance(obj, dict):
        return {k: redact_obj(v, compiled) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_obj(v, compiled) for v in obj]
    return obj


def dump_payload(kind: str, ts: int, system: str, user: str) -> None:
    """Write the exact outbound payload for user audit (§9.2, debug mode)."""
    paths.ensure_dirs()
    fn = paths.AI_PAYLOAD_DIR / f"{ts}_{kind}.json"
    try:
        fn.write_text(
            json.dumps({"kind": kind, "ts": ts, "system": system, "user": user},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError as e:
        _log.warning("could not write ai payload dump: %s", e)
