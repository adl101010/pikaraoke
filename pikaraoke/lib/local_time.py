"""Convert naive-UTC timestamps (SQLite CURRENT_TIMESTAMP) to local time for display."""

import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def _local_zone() -> ZoneInfo:
    try:
        return ZoneInfo(os.environ.get("TZ", "UTC"))
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _to_local(utc_str: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(utc_str).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return dt.astimezone(_local_zone())


def _hour(local_dt: datetime) -> str:
    return local_dt.strftime("%I").lstrip("0") or "12"


def format_local_datetime(utc_str: str | None) -> str:
    """Format a naive-UTC "YYYY-MM-DD HH:MM:SS" string in local time.

    Honors the TZ environment variable, e.g. "2026-07-29 9:30:12PM". Falls back
    to UTC if TZ is unset or invalid, and returns the input unchanged if it
    isn't a parseable timestamp.
    """
    if not utc_str:
        return ""
    local_dt = _to_local(utc_str)
    if local_dt is None:
        return utc_str
    return f"{local_dt.strftime('%Y-%m-%d')} {_hour(local_dt)}:{local_dt.strftime('%M:%S%p')}"


def format_local_clock(utc_str: str | None) -> str:
    """Just the local time of day, e.g. "9:30 PM", for times within one night."""
    if not utc_str:
        return ""
    local_dt = _to_local(utc_str)
    if local_dt is None:
        return utc_str
    return f"{_hour(local_dt)}:{local_dt.strftime('%M %p')}"
