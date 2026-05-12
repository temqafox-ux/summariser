from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo


def local_day_bounds_utc(
    local_date: dt.date,
    tz_name: str,
) -> tuple[int, int]:
    """Return (start_ts, end_ts) Unix UTC for [local midnight, next local midnight)."""
    tz = ZoneInfo(tz_name)
    start_local = dt.datetime.combine(local_date, dt.time.min, tzinfo=tz)
    end_local = start_local + dt.timedelta(days=1)
    start_utc = int(start_local.astimezone(dt.UTC).timestamp())
    end_utc = int(end_local.astimezone(dt.UTC).timestamp())
    return start_utc, end_utc


def yesterday(tz_name: str) -> dt.date:
    tz = ZoneInfo(tz_name)
    now = dt.datetime.now(tz).date()
    return now - dt.timedelta(days=1)


def today(tz_name: str) -> dt.date:
    tz = ZoneInfo(tz_name)
    return dt.datetime.now(tz).date()


def parse_iso_date(s: str) -> dt.date:
    return dt.date.fromisoformat(s)
