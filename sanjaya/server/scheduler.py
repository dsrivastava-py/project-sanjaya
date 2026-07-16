"""Background scheduler (PRD §5, §9.1). Runs the AI queue drain and retry loop;
Phase 5 adds the nightly journal and weekly-insight jobs. Uses APScheduler's
``BackgroundScheduler`` (a thread, not a second process — §12).

Every job opens its own SQLite connection (thread affinity) and builds a fresh
:class:`GroqClient`. When no ``GROQ_API_KEY`` is set, or the network is down, the
AI jobs no-op / requeue — the queue simply drains later, never crashing (§13.6).
"""
from __future__ import annotations

from .. import db as dbmod, env, goals as goalsmod, metrics, reporting
from ..ai import jobs
from ..ai.groq_client import GroqClient
from ..log import get
from ..timeutil import day_bounds, local_day, now_ts

_log = get("server.scheduler")

DRAIN_INTERVAL_S = 60      # ai_queue classify drain cadence
RETRY_INTERVAL_H = 1       # failed items reset to pending (§9.1)
SOAK_INTERVAL_S = 300      # perf self-metric log cadence (§15: every 5 min)
_MAX_BATCHES_PER_DRAIN = 20


class Scheduler:
    def __init__(self, cfg):
        self._cfg = cfg
        self._sched = None
        self._soak = metrics.SoakSampler()

    def start(self) -> None:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.interval import IntervalTrigger

        self._sched = BackgroundScheduler(timezone="UTC")
        self._sched.add_job(self._drain_classify, IntervalTrigger(seconds=DRAIN_INTERVAL_S),
                            id="drain_classify", max_instances=1, coalesce=True)
        self._sched.add_job(self._retry_failed, IntervalTrigger(hours=RETRY_INTERVAL_H),
                            id="retry_failed", max_instances=1, coalesce=True)

        hour, minute = self._summary_time()
        tz = self._cfg.timezone
        self._sched.add_job(self._nightly_summary,
                            CronTrigger(hour=hour, minute=minute, timezone=tz),
                            id="nightly_summary", max_instances=1, coalesce=True)
        # Weekly insight late Sunday, after that day's journal (§9.3 C).
        self._sched.add_job(self._weekly_insight,
                            CronTrigger(day_of_week="sun", hour=22, minute=30, timezone=tz),
                            id="weekly_insight", max_instances=1, coalesce=True)
        # Goals rollup just after the day boundary: cache the closed day's
        # progress in goal_progress (Phase 8; deterministic — no AI).
        self._sched.add_job(self._goals_rollup,
                            CronTrigger(hour=self._cfg.day_start_hour, minute=10, timezone=tz),
                            id="goals_rollup", max_instances=1, coalesce=True)
        # Retention trim (§7, Phase 9): drop raw spans older than
        # settings.retention_months once their day_summaries exist. 0 = never.
        self._sched.add_job(self._retention_trim,
                            CronTrigger(hour=self._cfg.day_start_hour, minute=25, timezone=tz),
                            id="retention_trim", max_instances=1, coalesce=True)
        # Perf soak log: dump self CPU%/RSS vs §12 budgets every 5 min (§15).
        self._sched.add_job(self._soak_log, IntervalTrigger(seconds=SOAK_INTERVAL_S),
                            id="soak_log", max_instances=1, coalesce=True)
        self._sched.start()
        _log.info("scheduler started (nightly summary %02d:%02d %s)", hour, minute, tz)

    def _summary_time(self) -> tuple[int, int]:
        raw = str(self._cfg.get("ai", "summary_time", "21:30"))
        try:
            h, m = raw.split(":")
            return int(h), int(m)
        except (ValueError, AttributeError):
            return 21, 30

    def shutdown(self) -> None:
        if self._sched is not None:
            self._sched.shutdown(wait=False)
            self._sched = None

    # -- jobs ----------------------------------------------------------------
    def _drain_classify(self) -> None:
        if not env.groq_api_key():
            return  # offline / not configured — leave the queue pending
        conn = dbmod.connect()
        try:
            client = GroqClient(self._cfg)
            for _ in range(_MAX_BATCHES_PER_DRAIN):
                res = jobs.run_classify_batch(conn, client, self._cfg)
                if not res.get("picked") or res.get("paused"):
                    break
        except Exception as e:  # noqa: BLE001 - a bad drain must not kill the scheduler
            _log.warning("classify drain error: %s", e)
        finally:
            conn.close()

    def _retry_failed(self) -> None:
        conn = dbmod.connect()
        try:
            conn.execute(
                "UPDATE ai_queue SET status='pending' WHERE status='failed' AND attempts < ?",
                (jobs.MAX_ATTEMPTS,),
            )
        finally:
            conn.close()

    def _nightly_summary(self) -> None:
        if not env.groq_api_key():
            return
        conn = dbmod.connect()
        try:
            cfg = self._cfg
            date = local_day(now_ts(), cfg.timezone, cfg.day_start_hour)
            jobs.summarize_day(conn, GroqClient(cfg), cfg, date, force=True)
            _log.info("nightly journal generated for %s", date)
        except Exception as e:  # noqa: BLE001
            _log.warning("nightly summary error: %s", e)
        finally:
            conn.close()

    def _weekly_insight(self) -> None:
        if not env.groq_api_key():
            return
        conn = dbmod.connect()
        try:
            cfg = self._cfg
            today = local_day(now_ts(), cfg.timezone, cfg.day_start_hour)
            ws = reporting.week_start_of(today)
            jobs.weekly_insight(conn, GroqClient(cfg), cfg, ws, force=True)
            _log.info("weekly insight generated for week of %s", ws)
        except Exception as e:  # noqa: BLE001
            _log.warning("weekly insight error: %s", e)
        finally:
            conn.close()

    def _goals_rollup(self) -> None:
        conn = dbmod.connect()
        try:
            n = goalsmod.rollup(conn, self._cfg)
            _log.info("goals rollup: %d period(s) cached", n)
        except Exception as e:  # noqa: BLE001
            _log.warning("goals rollup error: %s", e)
        finally:
            conn.close()

    def _soak_log(self) -> None:
        m = self._soak.sample()
        cpu = m.get("cpu_pct")
        rss = m.get("rss_mb")
        breach = (not m.get("cpu_ok", True)) or (not m.get("rss_ok", True))
        line = "soak: cpu=%s%% rss=%sMB threads=%s (budget cpu<%.1f%% rss<%dMB)"
        args = (cpu, rss, m.get("num_threads"),
                metrics.BUDGET_CPU_PCT, metrics.BUDGET_RSS_MB)
        if breach:
            _log.warning("BUDGET BREACH " + line, *args)
        else:
            _log.info(line, *args)

    def _retention_trim(self) -> None:
        conn = dbmod.connect()
        try:
            n = retention_trim(conn, self._cfg)
            if n:
                _log.info("retention trim: %d old span(s) removed", n)
        except Exception as e:  # noqa: BLE001
            _log.warning("retention trim error: %s", e)
        finally:
            conn.close()


def retention_trim(conn, cfg) -> int:
    """Delete spans older than ``retention_months``, but only day-by-day and only
    for days whose day_summaries row exists (never delete undocumented history;
    summaries are kept forever — §7). Returns rows removed. 0 disables."""
    raw = dbmod.get_setting(conn, "retention_months", None)
    months = int(raw) if raw is not None else int(cfg.get("privacy", "retention_months", 0))
    if months <= 0:
        return 0
    cutoff_day = local_day(now_ts() - months * 30 * 86400,
                           cfg.timezone, cfg.day_start_hour)
    days = [r["date"] for r in conn.execute(
        "SELECT date FROM day_summaries WHERE date < ? ORDER BY date", (cutoff_day,)
    ).fetchall()]
    removed = 0
    for d in days:
        lo, hi = day_bounds(d, cfg.timezone, cfg.day_start_hour)
        cur = conn.execute(
            "DELETE FROM spans WHERE start_ts >= ? AND end_ts <= ?", (lo, hi)
        )
        removed += cur.rowcount
    return removed
