from datetime import datetime, time
from zoneinfo import ZoneInfo

from app.services.digest.scheduler import (
    compute_evening_window,
    compute_morning_window,
)


def test_morning_window_covers_prior_22_to_07_in_org_tz():
    tz = ZoneInfo("Asia/Kolkata")
    now_local = datetime(2026, 5, 28, 7, 0, tzinfo=tz)
    start, end = compute_morning_window(now_local, morning_local_time=time(7, 0))
    assert start.tzinfo is not None
    assert end > start
    assert (end - start).total_seconds() == 9 * 3600


def test_evening_window_covers_07_to_19_in_org_tz():
    tz = ZoneInfo("Asia/Kolkata")
    now_local = datetime(2026, 5, 28, 19, 0, tzinfo=tz)
    start, end = compute_evening_window(now_local, evening_local_time=time(19, 0))
    assert (end - start).total_seconds() == 12 * 3600
