"""Deterministic rule engine (PRD §8.4).

Matching pipeline: first hit wins, ordered by ``priority`` (lower wins), then by
specificity ``url_prefix > domain > title_regex > exe``, then by longer pattern
(more specific) as a final tie-breaker. A match yields a category/project and an
optional ``kind_hint`` that overrides the parser's span kind.

The engine never overrides a user edit or an AI classification — that ordering is
enforced by the caller (rules run first at span close; §8.3).
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

# lower rank = more specific = checked first within equal priority
_SPECIFICITY = {"url_prefix": 0, "domain": 1, "title_regex": 2, "exe": 3}


@dataclass(frozen=True)
class Match:
    rule_id: int
    category_id: int | None
    project_id: int | None
    kind_hint: str | None


def _domain_matches(domain: str | None, pattern: str) -> bool:
    if not domain:
        return False
    d = domain.lower()
    p = pattern.lower()
    return d == p or d.endswith("." + p)


class RulesEngine:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._rules: list[dict] = []
        self.reload()

    def reload(self) -> None:
        """(Re)load and sort rules; compile title regexes once."""
        rows = self._conn.execute(
            "SELECT id, priority, matcher, pattern, kind_hint, category_id, "
            "project_id FROM rules"
        ).fetchall()
        rules = []
        for r in rows:
            d = dict(r)
            if d["matcher"] == "title_regex":
                try:
                    d["_rx"] = re.compile(d["pattern"])
                except re.error:
                    continue  # skip a malformed user regex rather than crash
            rules.append(d)
        rules.sort(key=lambda d: (
            d["priority"],
            _SPECIFICITY.get(d["matcher"], 9),
            -len(d["pattern"]),
        ))
        self._rules = rules

    def classify(self, *, kind: str | None = None, exe: str | None = None,
                 domain: str | None = None, url: str | None = None,
                 title: str | None = None) -> Match | None:
        """Return the first matching rule, or None."""
        exe_l = (exe or "").lower()
        for d in self._rules:
            m = d["matcher"]
            pat = d["pattern"]
            hit = (
                (m == "exe" and exe_l == pat.lower()) or
                (m == "domain" and _domain_matches(domain, pat)) or
                (m == "url_prefix" and bool(url) and url.startswith(pat)) or
                (m == "title_regex" and bool(title) and bool(d["_rx"].search(title)))
            )
            if hit:
                return Match(d["id"], d["category_id"], d["project_id"], d["kind_hint"])
        return None

    def record_hit(self, rule_id: int) -> None:
        self._conn.execute(
            "UPDATE rules SET hit_count = hit_count + 1 WHERE id = ?", (rule_id,)
        )
