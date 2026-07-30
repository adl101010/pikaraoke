"""Unit tests for local_time."""

from pikaraoke.lib.local_time import format_local_datetime


def test_empty_input_returns_empty_string():
    assert format_local_datetime(None) == ""
    assert format_local_datetime("") == ""


def test_unparseable_input_returned_unchanged():
    assert format_local_datetime("not a timestamp") == "not a timestamp"


def test_converts_utc_to_configured_timezone(monkeypatch):
    monkeypatch.setenv("TZ", "America/Chicago")
    # 2026-07-30 02:30:12 UTC is 2026-07-29 21:30:12 CDT (UTC-5 in summer)
    assert format_local_datetime("2026-07-30 02:30:12") == "2026-07-29 9:30:12PM"


def test_midnight_and_noon_use_12_not_00(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    assert format_local_datetime("2026-07-30 00:05:00") == "2026-07-30 12:05:00AM"
    assert format_local_datetime("2026-07-30 12:05:00") == "2026-07-30 12:05:00PM"


def test_falls_back_to_utc_when_tz_unset(monkeypatch):
    monkeypatch.delenv("TZ", raising=False)
    assert format_local_datetime("2026-07-30 02:30:12") == "2026-07-30 2:30:12AM"


def test_falls_back_to_utc_when_tz_invalid(monkeypatch):
    monkeypatch.setenv("TZ", "Not/AZone")
    assert format_local_datetime("2026-07-30 02:30:12") == "2026-07-30 2:30:12AM"
