from datetime import datetime, timezone
from typing import Optional


MINUTE_SECONDS = 60
HOUR_SECONDS = 60 * MINUTE_SECONDS
DAY_SECONDS = 24 * HOUR_SECONDS
WEEK_SECONDS = 7 * DAY_SECONDS


def friendly_time(value: str, now: Optional[datetime] = None) -> str:
    """Format a timestamp as a compact, human-friendly relative label."""
    text = value.strip()
    if not text:
        return "unknown"

    timestamp = _parse_timestamp(text)
    if timestamp is None:
        return text

    current = now or datetime.now().astimezone()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timestamp.tzinfo)

    seconds = int((current - timestamp).total_seconds())
    if seconds < 0:
        return _future_time(-seconds, timestamp, current)
    return _past_time(seconds, timestamp, current)


def _parse_timestamp(text: str) -> Optional[datetime]:
    try:
        return datetime.fromtimestamp(float(text), tz=timezone.utc).astimezone()
    except (OSError, OverflowError, ValueError):
        pass

    iso_text = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        timestamp = datetime.fromisoformat(iso_text)
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp


def _past_time(seconds: int, timestamp: datetime, current: datetime) -> str:
    if seconds < MINUTE_SECONDS:
        return "just now"
    if seconds < HOUR_SECONDS:
        return "{0}m ago".format(max(1, seconds // MINUTE_SECONDS))
    if seconds < DAY_SECONDS:
        return "{0}h ago".format(max(1, seconds // HOUR_SECONDS))
    if seconds < WEEK_SECONDS:
        return "{0}d ago".format(max(1, seconds // DAY_SECONDS))
    return _date_text(timestamp, current)


def _future_time(seconds: int, timestamp: datetime, current: datetime) -> str:
    if seconds < MINUTE_SECONDS:
        return "soon"
    if seconds < HOUR_SECONDS:
        return "in {0}m".format(max(1, seconds // MINUTE_SECONDS))
    if seconds < DAY_SECONDS:
        return "in {0}h".format(max(1, seconds // HOUR_SECONDS))
    if seconds < WEEK_SECONDS:
        return "in {0}d".format(max(1, seconds // DAY_SECONDS))
    return _date_text(timestamp, current)


def _date_text(timestamp: datetime, current: datetime) -> str:
    month_day = "{0} {1}".format(timestamp.strftime("%b"), timestamp.day)
    if timestamp.year == current.year:
        return month_day
    return "{0}, {1}".format(month_day, timestamp.year)
