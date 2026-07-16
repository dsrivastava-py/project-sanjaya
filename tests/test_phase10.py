"""Phase 10 acceptance tests (PRD §14/§15): perf self-metrics + onboarding gate.

Covers the self-metric surface the soak relies on: :func:`metrics.self_metrics`
shape + budget flags, :class:`metrics.SoakSampler` producing a CPU% on its second
sample, ``/status`` exposing the ``process`` block, and the ``onboarding_done``
settings gate the first-run overlay reads.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from sanjaya import config as configmod, db as dbmod, metrics
from sanjaya.runtime import RuntimeState
from sanjaya.server.app import create_app


@pytest.fixture()
def client(monkeypatch, tmp_path):
    path = tmp_path / "api.db"
    real_connect = dbmod.connect

    def connect(p=None):
        return real_connect(path if p is None else p)

    monkeypatch.setattr(dbmod, "connect", connect)
    dbmod.init_db(path)
    cfg = configmod.load(create=False)
    return TestClient(create_app(cfg, RuntimeState(), controller=None))


# --- self-metrics (§12 budgets, §15 soak) ------------------------------------
def test_self_metrics_shape_and_budget_flags():
    m = metrics.self_metrics()
    assert set(m) >= {"cpu_pct", "rss_mb", "num_threads",
                      "budget_cpu_pct", "budget_rss_mb", "cpu_ok", "rss_ok"}
    assert m["budget_cpu_pct"] == metrics.BUDGET_CPU_PCT == 0.5
    assert m["budget_rss_mb"] == metrics.BUDGET_RSS_MB == 150
    # a live python process has a real RSS well under the 150MB budget
    assert m["rss_mb"] is not None and 0 < m["rss_mb"] < 150
    assert m["rss_ok"] is True


def test_soak_sampler_reports_cpu_on_second_sample():
    s = metrics.SoakSampler()
    first = s.sample()
    assert first["cpu_pct"] is None          # no baseline yet
    # burn a little CPU so the delta is measurable
    x = 0
    for i in range(200_000):
        x += i * i
    second = s.sample()
    assert second["cpu_pct"] is not None
    assert second["cpu_pct"] >= 0.0
    assert second["rss_mb"] is not None


def test_status_endpoint_exposes_process_block(client):
    r = client.get("/api/status")
    assert r.status_code == 200
    proc = r.json()["process"]
    assert proc["budget_cpu_pct"] == 0.5
    assert proc["budget_rss_mb"] == 150
    assert "rss_mb" in proc and "cpu_ok" in proc


# --- onboarding gate (§14 Phase 10) ------------------------------------------
def test_onboarding_gate_defaults_false_then_persists(client):
    settings = client.get("/api/settings").json()["settings"]
    assert settings["onboarding_done"] is False
    r = client.patch("/api/settings", json={"onboarding_done": True})
    assert r.status_code == 200
    assert r.json()["settings"]["onboarding_done"] is True
    # survives a re-read
    assert client.get("/api/settings").json()["settings"]["onboarding_done"] is True
