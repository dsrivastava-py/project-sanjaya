"""Privacy settings enforcement (PRD §9.2, §10.6, §13.10).

Excluded apps/domains still produce honest foreground spans, but titles/details/URLs
are replaced before persistence and the AI queue never receives them.
"""
from __future__ import annotations

import json
from fnmatch import fnmatch
from urllib.parse import urlparse

from . import db as dbmod

EXCLUDED_TITLE = "[excluded]"

DEFAULT_EXCLUDED_EXES = ["1password.exe", "keepass*.exe"]
DEFAULT_EXCLUDED_DOMAINS = [
    "1password.com", "accounts.google.com", "netbanking.hdfcbank.com",
    "icicibank.com", "onlinesbi.sbi", "axisbank.com", "kotak.com",
]
DEFAULT_REDACTION_PATTERNS: list[str] = []


_JSON_KEYS = {
    "exclude_exes": DEFAULT_EXCLUDED_EXES,
    "exclude_domains": DEFAULT_EXCLUDED_DOMAINS,
    "redaction_patterns": DEFAULT_REDACTION_PATTERNS,
}


def _json_setting(conn, key: str, default):
    raw = dbmod.get_setting(conn, key, None)
    if raw is None:
        return list(default) if isinstance(default, list) else default
    try:
        val = json.loads(raw)
    except (TypeError, ValueError):
        return list(default) if isinstance(default, list) else default
    return val if isinstance(val, type(default)) else default


def list_setting(conn, key: str) -> list[str]:
    vals = _json_setting(conn, key, _JSON_KEYS.get(key, []))
    if not isinstance(vals, list):
        return []
    return [str(v).strip() for v in vals if str(v).strip()]


def domain_of(url: str | None) -> str | None:
    if not url:
        return None
    try:
        host = urlparse(url).hostname
    except ValueError:
        return None
    return host.lower() if host else None


def _domain_matches(domain: str, pattern: str) -> bool:
    d, p = domain.lower(), pattern.lower().lstrip(".")
    return d == p or d.endswith("." + p) or fnmatch(d, p)


def is_excluded(conn, *, exe: str | None = None, domain: str | None = None, url: str | None = None) -> bool:
    ex = (exe or "").lower()
    dom = (domain or domain_of(url) or "").lower()
    for pat in list_setting(conn, "exclude_exes"):
        if ex and fnmatch(ex, pat.lower()):
            return True
    for pat in list_setting(conn, "exclude_domains"):
        if dom and _domain_matches(dom, pat):
            return True
    return False


def scrub_span(conn, span: dict) -> dict:
    """Mutate an in-flight span if it matches the exclusion list."""
    if not is_excluded(conn, exe=span.get("exe"), domain=span.get("domain"), url=span.get("url")):
        span["_excluded"] = False
        return span
    span["kind"] = "app"
    span["window_title"] = EXCLUDED_TITLE
    span["url"] = None
    span["domain"] = domain_of(span.get("url")) or span.get("domain")
    span["detail"] = None
    span["category_id"] = None
    span["project_id"] = None
    span["classified_by"] = None
    span["rule_id"] = None
    span["ai_confidence"] = None
    span["_excluded"] = True
    return span


def default_settings_payload() -> dict:
    return {k: list(v) for k, v in _JSON_KEYS.items()}
