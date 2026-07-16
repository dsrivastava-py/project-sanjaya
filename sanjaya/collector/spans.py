"""Span builder / flusher (PRD §8.3).

Consumes a stream of foreground observations and emits *spans* — contiguous
blocks of one activity — into SQLite. Responsibilities:

  * identity keying: consecutive same-identity samples extend the open span;
    a change closes it and opens a new one. Key = (exe, url) when a URL is known
    (extension), else (exe, title_hash).
  * flicker rule: an active span shorter than ``flicker_min_s`` at close is
    absorbed — its time folds into a neighbor, no DB row is created — so rapid
    alt-tabbing never litters the timeline (§13.4).
  * durability: the open span is flushed every ``flush_interval_s`` so a crash
    loses at most that many seconds. Sub-flicker spans aren't flushed, so they
    can still be absorbed.
  * classification at close: rules engine first (§8.4); an unmatched span keeps
    ``category_id = NULL`` and is handed to ``enqueue_unknown`` for the AI queue.

The builder is transport-agnostic: the collector loop feeds it via ``on_active``
/ ``on_idle`` / ``on_locked`` and calls ``tick`` / ``shutdown``.
"""
from __future__ import annotations

import sqlite3
from typing import Callable

from .. import db as dbmod
from .. import privacy
from ..log import get
from . import parsers

_log = get("collector.spans")

_ACTIVE_KINDS_EXCLUDED_FROM_CLASSIFY = {"idle", "locked", "manual"}


class SpanBuilder:
    def __init__(self, conn: sqlite3.Connection, engine, *,
                 flicker_min_s: int = 5, flush_interval_s: int = 5,
                 enqueue_unknown: Callable[[dict], None] | None = None):
        self._conn = conn
        self._engine = engine
        self._flicker = flicker_min_s
        self._flush_interval = flush_interval_s
        self._enqueue_unknown = enqueue_unknown

        self._open: dict | None = None          # current in-progress span
        self._prev: dict | None = None          # last committed span (for merges)
        self._last_flush_ts = 0

    # -- public feed ---------------------------------------------------------
    def on_active(self, ts: int, exe: str | None, app_name: str | None,
                  title: str | None, url: str | None = None,
                  domain: str | None = None, ext_detail: dict | None = None) -> None:
        parsed = parsers.parse(exe, app_name, title, url, domain)
        identity = (exe, url) if url else (exe, parsers.title_hash(title or ""))
        detail = dict(parsed["detail"] or {})
        if ext_detail:  # §8.8 reconciliation: extension enriches (channel, position, real title)
            detail.update({k: v for k, v in ext_detail.items() if v is not None})
        span = {
            "start_ts": ts, "end_ts": ts,
            "kind": parsed["kind"], "exe": exe, "app_name": app_name,
            "window_title": title, "url": parsed["url"], "domain": parsed["domain"],
            "detail": detail or None,
            "category_id": None, "project_id": None,
            "classified_by": None, "rule_id": None, "ai_confidence": None,
            "edited": 0, "_identity": identity, "_id": None,
        }
        privacy.scrub_span(self._conn, span)
        if span.get("_excluded"):
            identity = ("excluded", exe, span.get("domain") or privacy.domain_of(url))
            span["_identity"] = identity
        self._advance(ts, span)

    def on_idle(self, ts: int, idle_since_ts: int) -> None:
        self._advance(ts, self._synthetic("idle", idle_since_ts, ts), boundary=idle_since_ts)

    def on_locked(self, ts: int) -> None:
        self._advance(ts, self._synthetic("locked", ts, ts))

    def tick(self, ts: int) -> None:
        """Periodic flush of the open span (bounds crash loss)."""
        if self._open is None:
            return
        if ts - self._last_flush_ts >= self._flush_interval and \
                self._open["end_ts"] - self._open["start_ts"] >= self._flush_interval:
            self._persist(self._open)
            self._last_flush_ts = ts

    def shutdown(self, ts: int) -> None:
        """Close the open span at ``ts`` and persist (graceful quit)."""
        if self._open is not None:
            self._open["end_ts"] = max(self._open["end_ts"], ts)
            self._commit(self._open)
            self._open = None

    # -- internals -----------------------------------------------------------
    def _synthetic(self, kind: str, start_ts: int, end_ts: int) -> dict:
        return {
            "start_ts": start_ts, "end_ts": end_ts, "kind": kind,
            "exe": None, "app_name": None, "window_title": None,
            "url": None, "domain": None, "detail": None,
            "category_id": None, "project_id": None, "classified_by": None,
            "rule_id": None, "ai_confidence": None, "edited": 0,
            "_identity": (kind,), "_id": None,
        }

    def _advance(self, ts: int, new: dict, boundary: int | None = None) -> None:
        """Extend the open span, or close it and start ``new``."""
        cut = boundary if boundary is not None else ts
        if self._open is None:
            self._open = new
            return

        if self._open["_identity"] == new["_identity"]:
            # same activity -> extend
            self._open["end_ts"] = max(self._open["end_ts"], ts)
            if new["kind"] not in ("idle", "locked"):
                self._enrich(self._open, new)
            return

        # identity changed -> the open span ends at the boundary
        self._open["end_ts"] = max(self._open["start_ts"], cut)
        end = self._open["end_ts"]
        is_active = self._open["kind"] not in ("idle", "locked")
        flicker = is_active and self._open["_id"] is None and (end - self._open["start_ts"]) < self._flicker

        if flicker and self._prev is not None and self._prev["_identity"] == new["_identity"]:
            # bounce back to the previous activity -> keep it one continuous span
            self._prev["end_ts"] = max(self._prev["end_ts"], ts)
            self._persist(self._prev)
            self._open = self._prev
            return

        if flicker:
            # drop the flicker span; credit its elapsed time to the previous span
            if self._prev is not None:
                self._prev["end_ts"] = end
                self._persist(self._prev)
        else:
            self._commit(self._open)

        new["start_ts"] = end
        new["end_ts"] = max(new["end_ts"], new["start_ts"])
        self._open = new
        self._last_flush_ts = new["start_ts"]

    def _enrich(self, open_span: dict, sample: dict) -> None:
        """Fill in richer detail if a later sample of the same identity has it
        (e.g. the window title finished loading)."""
        if not open_span.get("window_title") and sample.get("window_title"):
            open_span["window_title"] = sample["window_title"]
        if not open_span.get("detail") and sample.get("detail"):
            open_span["detail"] = sample["detail"]

    def _commit(self, span: dict) -> None:
        # persist first so the row has an id, then classify (an unmatched span is
        # enqueued for AI by id), then persist the classification.
        self._persist(span)
        self._classify(span)
        self._persist(span)
        self._prev = span

    def _classify(self, span: dict) -> None:
        if span.get("_excluded"):
            return
        if span["kind"] in _ACTIVE_KINDS_EXCLUDED_FROM_CLASSIFY:
            return
        m = self._engine.classify(
            kind=span["kind"], exe=span["exe"], domain=span["domain"],
            url=span["url"], title=span["window_title"],
        )
        if m is not None:
            if m.kind_hint:
                span["kind"] = m.kind_hint
            span["category_id"] = m.category_id
            span["project_id"] = m.project_id
            span["classified_by"] = "rule"
            span["rule_id"] = m.rule_id
            self._engine.record_hit(m.rule_id)
        if span["category_id"] is None and self._enqueue_unknown is not None:
            self._enqueue_unknown(span)

    def _persist(self, span: dict) -> None:
        try:
            if span["_id"] is None:
                span["_id"] = dbmod.insert_span(self._conn, span)
            else:
                dbmod.update_span(self._conn, span["_id"], span)
        except sqlite3.Error as e:  # DB locked etc. — never crash the loop
            _log.warning("span persist failed: %s", e)
