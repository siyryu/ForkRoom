from datetime import datetime, timedelta, timezone

from forkroom.time_format import friendly_time


NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)


def ago(**kwargs: int) -> str:
    return (NOW - timedelta(**kwargs)).isoformat()


def ahead(**kwargs: int) -> str:
    return (NOW + timedelta(**kwargs)).isoformat()


def test_empty_time_is_unknown() -> None:
    assert friendly_time("", now=NOW) == "unknown"


def test_unparseable_time_is_preserved() -> None:
    assert friendly_time("not-a-time", now=NOW) == "not-a-time"


def test_recent_time_displays_as_just_now() -> None:
    assert friendly_time(ago(seconds=30), now=NOW) == "just now"


def test_same_day_time_displays_minutes_or_hours_ago() -> None:
    assert friendly_time(ago(minutes=12), now=NOW) == "12m ago"
    assert friendly_time(ago(hours=3), now=NOW) == "3h ago"


def test_same_week_time_displays_days_ago() -> None:
    assert friendly_time(ago(days=3, minutes=5), now=NOW) == "3d ago"


def test_older_time_displays_month_and_day_for_current_year() -> None:
    assert friendly_time(ago(days=8), now=NOW) == "Jun 7"


def test_older_time_displays_year_when_needed() -> None:
    assert friendly_time("2025-06-15T12:00:00+00:00", now=NOW) == "Jun 15, 2025"


def test_future_time_uses_relative_labels_inside_week() -> None:
    assert friendly_time(ahead(hours=2), now=NOW) == "in 2h"
