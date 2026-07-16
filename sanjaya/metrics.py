"""Self-process metrics for the perf budget (§12, §15).

Sanjaya is one process — the collector thread and the FastAPI server share it —
so our own :class:`psutil.Process` footprint is exactly the "collector+server"
number the budget targets. CPU% is a delta of ``cpu_times()`` between calls,
normalized to total machine capacity (all cores) to match Task Manager.

Two independent samplers with their own baseline state:

* :func:`self_metrics` — cheap, best-effort, for the ``/status`` endpoint
  (instantaneous CPU% since the previous ``/status`` call).
* :class:`SoakSampler` — dedicated baseline for the 5-minute soak log so a busy
  dashboard polling ``/status`` cannot skew the averaging window (§15).

Metrics never raise: any failure degrades to ``None`` so ``/status`` stays up.
"""
from __future__ import annotations

import threading
import time

# hard budgets (§12) surfaced alongside the reading so the UI/soak can flag breach
BUDGET_CPU_PCT = 0.5
BUDGET_RSS_MB = 150

_lock = threading.Lock()
_proc = None
_last: tuple[float, float] | None = None   # (monotonic_ts, cpu_seconds)


def _process():
    global _proc
    if _proc is None:
        import psutil
        _proc = psutil.Process()
    return _proc


def _cpu_pct(p, state: tuple[float, float] | None) -> tuple[float | None, tuple[float, float]]:
    """Return (percent-of-total-capacity, new baseline). First call → None."""
    import psutil
    now = time.monotonic()
    t = p.cpu_times()
    cpu_s = float(t.user + t.system)
    pct = None
    if state is not None:
        dt = now - state[0]
        if dt > 0:
            cores = psutil.cpu_count() or 1
            pct = round((cpu_s - state[1]) / dt / cores * 100.0, 3)
    return pct, (now, cpu_s)


def self_metrics() -> dict:
    """Snapshot for ``/status``. Best-effort; shared baseline across calls."""
    global _last
    try:
        import psutil  # noqa: F401
        p = _process()
        with _lock:
            pct, _last = _cpu_pct(p, _last)
            rss_mb = round(p.memory_info().rss / 1024 / 1024, 1)
            threads = p.num_threads()
        return {
            "cpu_pct": pct,
            "rss_mb": rss_mb,
            "num_threads": threads,
            "budget_cpu_pct": BUDGET_CPU_PCT,
            "budget_rss_mb": BUDGET_RSS_MB,
            "cpu_ok": (pct is None) or pct <= BUDGET_CPU_PCT,
            "rss_ok": rss_mb <= BUDGET_RSS_MB,
        }
    except Exception:  # noqa: BLE001 — metrics must never break /status
        return {
            "cpu_pct": None, "rss_mb": None, "num_threads": None,
            "budget_cpu_pct": BUDGET_CPU_PCT, "budget_rss_mb": BUDGET_RSS_MB,
            "cpu_ok": True, "rss_ok": True,
        }


class SoakSampler:
    """5-minute soak sampler with its own CPU baseline (§15). Each :meth:`sample`
    reports CPU% averaged over the interval since the previous sample."""

    def __init__(self) -> None:
        self._p = None
        self._state: tuple[float, float] | None = None

    def sample(self) -> dict:
        try:
            import psutil
            if self._p is None:
                self._p = psutil.Process()
            pct, self._state = _cpu_pct(self._p, self._state)
            rss_mb = round(self._p.memory_info().rss / 1024 / 1024, 1)
            return {
                "cpu_pct": pct,
                "rss_mb": rss_mb,
                "num_threads": self._p.num_threads(),
                "cpu_ok": (pct is None) or pct <= BUDGET_CPU_PCT,
                "rss_ok": rss_mb <= BUDGET_RSS_MB,
            }
        except Exception:  # noqa: BLE001
            return {"cpu_pct": None, "rss_mb": None, "num_threads": None,
                    "cpu_ok": True, "rss_ok": True}
