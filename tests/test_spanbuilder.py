"""Span-builder integration (PRD §8.3, §15): drive scripted samples through the
builder and assert span shape, flicker absorption, idle/lock handling, durability,
and rule classification coverage. Pure/deterministic — no Windows APIs.
"""
from __future__ import annotations

from sanjaya.collector.spans import SpanBuilder
from sanjaya.rules.engine import RulesEngine


def _builder(db):
    return SpanBuilder(db, RulesEngine(db), flicker_min_s=5, flush_interval_s=5)


def _rows(db):
    return db.execute(
        "SELECT id, kind, exe, domain, category_id, duration_s, start_ts, end_ts "
        "FROM spans ORDER BY start_ts"
    ).fetchall()


def _feed_active(b, exe, app, title, t0, t1, url=None, domain=None, step=2):
    for ts in range(t0, t1 + 1, step):
        b.on_active(ts, exe, app, title, url=url, domain=domain)
        b.tick(ts)  # mirror the collector loop's periodic flush


def test_full_scripted_day(db):
    b = _builder(db)
    # 1000-1060 GitHub (code / Building)
    _feed_active(b, "chrome.exe", "Chrome", "GitHub - repo", 1000, 1060,
                 url="https://github.com/a/b", domain="github.com")
    # 1060-1120 VLC (media / Entertainment)
    _feed_active(b, "vlc.exe", "VLC", "movie.mkv", 1062, 1120)
    # 3s flicker to Notepad, then back to VLC -> absorbed, no notepad row
    b.on_active(1122, "notepad.exe", "Notepad", "untitled")
    _feed_active(b, "vlc.exe", "VLC", "movie.mkv", 1124, 1200)
    # idle 1200-1300 (last input at 1200)
    b.on_idle(1290, 1200)
    # 1300-1400 VS Code (code / Building)
    _feed_active(b, "Code.exe", "VS Code", "app.py — proj — Visual Studio Code", 1300, 1400)
    b.shutdown(1400)

    rows = _rows(db)
    kinds = [r["kind"] for r in rows]

    # no notepad flicker survived
    assert not any(r["exe"] == "notepad.exe" for r in rows)
    # idle span exists
    assert "idle" in kinds
    # durations sum to wall clock (1000..1400 = 400s) within 1%
    total = sum(r["duration_s"] for r in rows)
    assert abs(total - 400) <= 4
    # timeline is contiguous (no gaps/overlaps)
    for a, c in zip(rows, rows[1:]):
        assert a["end_ts"] == c["start_ts"]

    # every active (non-idle) span is auto-categorized by rules -> >=80%
    active = [r for r in rows if r["kind"] not in ("idle", "locked")]
    categorized = [r for r in active if r["category_id"] is not None]
    assert len(categorized) / len(active) >= 0.8


def test_kind_hint_applied(db):
    b = _builder(db)
    _feed_active(b, "chrome.exe", "Chrome", "GitHub - repo", 0, 60,
                 url="https://github.com/a/b", domain="github.com")
    b.shutdown(60)
    row = _rows(db)[0]
    assert row["kind"] == "code"  # rule kind_hint overrode 'web'


def test_lock_creates_locked_span(db):
    b = _builder(db)
    _feed_active(b, "chrome.exe", "Chrome", "x", 0, 20)
    b.on_locked(22)
    b.on_locked(32)
    _feed_active(b, "chrome.exe", "Chrome", "x", 40, 60)
    b.shutdown(60)
    assert "locked" in [r["kind"] for r in _rows(db)]


def test_durability_flush_persists_before_close(db):
    # a crash before shutdown must lose <=flush_interval of the open span
    b = _builder(db)
    _feed_active(b, "chrome.exe", "Chrome", "GitHub - repo", 0, 30,
                 url="https://github.com/a/b", domain="github.com")
    # no shutdown() == simulated kill -9; the periodic flush should have persisted
    rows = _rows(db)
    assert rows, "open span should have been flushed at least once"
    assert rows[-1]["end_ts"] >= 25  # within 5s of the last sample at t=30
