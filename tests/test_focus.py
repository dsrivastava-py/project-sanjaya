"""Focus-score tests (PRD §8.6): the deterministic formula and its components."""
from __future__ import annotations

from sanjaya import focus


def span(start, end, *, exe="a.exe", kind="app", project=None, prod=1):
    return {"start_ts": start, "end_ts": end, "exe": exe, "kind": kind,
            "project_id": project, "is_productive": prod}


def test_empty_day_is_zero():
    assert focus.score([]) == 0.0


def test_idle_only_is_zero():
    assert focus.score([span(0, 3600, kind="idle", prod=0)]) == 0.0


def test_perfect_day_is_100():
    # 90 min single-project productive block, no switches
    c = focus.components([span(0, 5400, exe="code.exe", project=1, prod=1)])
    assert c["P"] == 1.0 and c["D"] == 1.0 and c["S"] == 1.0
    assert c["score"] == 100.0


def test_productive_fraction():
    spans = [span(0, 3600, exe="code.exe", project=1, prod=1),
             span(3600, 7200, exe="vlc.exe", project=None, prod=0)]
    c = focus.components(spans)
    assert c["P"] == 0.5
    assert round(c["D"], 3) == round((3600 / 60) / 90, 3)  # 60min block / 90


def test_switches_floor_S_to_zero():
    # 30 x 1min spans alternating exe -> 58 switches/hour over 0.5h -> S=0
    spans = []
    for i in range(30):
        spans.append(span(i * 60, (i + 1) * 60, exe="a.exe" if i % 2 else "b.exe",
                          project=None, prod=1))
    c = focus.components(spans)
    assert c["P"] == 1.0 and c["D"] == 0.0 and c["S"] == 0.0
    assert c["score"] == 50.0


def test_flicker_ignored_in_switch_count():
    spans = [span(0, 60, exe="a.exe"), span(60, 63, exe="c.exe"),  # 3s flicker
             span(63, 123, exe="a.exe")]
    assert focus.components(spans)["switches"] == 0


def test_deep_block_tolerates_short_interruption():
    spans = [span(0, 1500, project=1), span(1560, 3000, project=1)]  # 60s gap < 120
    assert focus.components(spans)["longest_deep_s"] == 3000


def test_deep_block_breaks_on_long_interruption():
    spans = [span(0, 1500, project=1), span(1620, 3000, project=1)]  # 120s gap
    # neither cluster alone reaches... first is exactly 25min (qualifies), second 23min
    assert focus.components(spans)["longest_deep_s"] == 1500


def test_no_project_no_deep_block():
    assert focus.components([span(0, 6000, project=None)])["longest_deep_s"] == 0
