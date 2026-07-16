"""Time helpers. All timestamps in the DB are UTC epoch seconds (INTEGER);
rendering/day-bucketing converts to the configured local zone (PRD §7).
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def now_ts() -> int:
    """Current UTC epoch seconds (integer)."""
    return int(time.time())


def local_dt(ts: int, tz: str) -> datetime:
    return datetime.fromtimestamp(ts, ZoneInfo(tz))


def local_day(ts: int, tz: str, day_start_hour: int = 4) -> str:
    """Local calendar day 'YYYY-MM-DD' for a timestamp, honoring day_start_hour
    so an early-morning session before the cutoff counts to the previous day.
    """
    dt = local_dt(ts, tz) - timedelta(hours=day_start_hour)
    return dt.strftime("%Y-%m-%d")


def day_bounds(date: str, tz: str, day_start_hour: int = 4) -> tuple[int, int]:
    """[start_ts, end_ts) UTC epoch bounds for a local calendar day."""
    zone = ZoneInfo(tz)
    d = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=zone)
    start = d + timedelta(hours=day_start_hour)
    end = start + timedelta(days=1)
    return int(start.timestamp()), int(end.timestamp())
