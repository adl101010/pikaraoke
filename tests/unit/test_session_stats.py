"""Unit tests for session_stats (session-history computation)."""

from datetime import datetime
from unittest.mock import patch

import pytest

from pikaraoke.lib.karaoke_database import KaraokeDatabase
from pikaraoke.lib.session_stats import (
    clear_sessions_cache,
    compute_all_sessions,
    get_sessions,
    is_session_live,
)


def _event(file_path: str, user: str, played_at: str) -> dict:
    return {"file_path": file_path, "user": user, "played_at": played_at}


class TestComputeAllSessions:
    def test_empty_when_no_events(self):
        assert compute_all_sessions([]) == []

    def test_single_event_is_its_own_session(self):
        events = [_event("/a.mp4", "Alice", "2026-01-01 20:00:00")]
        sessions = compute_all_sessions(events)
        assert len(sessions) == 1
        assert sessions[0].play_count == 1
        assert sessions[0].started_at == "2026-01-01 20:00:00"
        assert sessions[0].ended_at == "2026-01-01 20:00:00"

    def test_groups_events_within_gap_threshold(self):
        events = [
            _event("/a.mp4", "Alice", "2026-01-01 20:00:00"),
            _event("/b.mp4", "Bob", "2026-01-01 20:30:00"),
            _event("/c.mp4", "Carol", "2026-01-01 21:00:00"),
        ]
        sessions = compute_all_sessions(events, gap_hours=1.0)
        assert len(sessions) == 1
        assert sessions[0].play_count == 3
        assert sessions[0].started_at == "2026-01-01 20:00:00"
        assert sessions[0].ended_at == "2026-01-01 21:00:00"

    def test_splits_into_separate_sessions_across_a_long_gap(self):
        events = [
            _event("/old.mp4", "Alice", "2026-01-01 10:00:00"),  # last night
            _event("/a.mp4", "Bob", "2026-01-02 20:00:00"),
            _event("/b.mp4", "Carol", "2026-01-02 20:30:00"),
        ]
        sessions = compute_all_sessions(events, gap_hours=1.0)
        assert len(sessions) == 2
        assert sessions[0].play_count == 1
        assert sessions[0].started_at == "2026-01-01 10:00:00"
        assert sessions[1].play_count == 2
        assert sessions[1].started_at == "2026-01-02 20:00:00"

    def test_sessions_returned_oldest_first(self):
        events = [
            _event("/old.mp4", "Alice", "2026-01-01 10:00:00"),
            _event("/new.mp4", "Bob", "2026-01-05 10:00:00"),
        ]
        sessions = compute_all_sessions(events, gap_hours=1.0)
        assert sessions[0].started_at == "2026-01-01 10:00:00"
        assert sessions[1].started_at == "2026-01-05 10:00:00"

    def test_counts_unique_singers(self):
        events = [
            _event("/a.mp4", "Alice", "2026-01-01 20:00:00"),
            _event("/b.mp4", "Alice", "2026-01-01 20:05:00"),
            _event("/c.mp4", "Bob", "2026-01-01 20:10:00"),
        ]
        sessions = compute_all_sessions(events)
        assert sessions[0].singer_count == 2

    def test_top_songs_and_singers_ranked_by_count(self):
        events = [
            _event("/a.mp4", "Alice", "2026-01-01 20:00:00"),
            _event("/a.mp4", "Bob", "2026-01-01 20:05:00"),
            _event("/b.mp4", "Bob", "2026-01-01 20:10:00"),
        ]
        sessions = compute_all_sessions(events)
        assert sessions[0].top_songs[0] == ("/a.mp4", 2)
        assert sessions[0].top_singers[0] == ("Bob", 2)

    def test_ignores_blank_users_for_singer_stats(self):
        events = [
            _event("/a.mp4", "", "2026-01-01 20:00:00"),
            _event("/b.mp4", "Alice", "2026-01-01 20:05:00"),
        ]
        sessions = compute_all_sessions(events)
        assert sessions[0].play_count == 2
        assert sessions[0].singer_count == 1

    def test_songs_by_singer_groups_each_users_songs(self):
        events = [
            _event("/a.mp4", "Alice", "2026-01-01 20:00:00"),
            _event("/b.mp4", "Alice", "2026-01-01 20:05:00"),
            _event("/c.mp4", "Bob", "2026-01-01 20:10:00"),
        ]
        sessions = compute_all_sessions(events)
        assert set(sessions[0].songs_by_singer["Alice"]) == {("/a.mp4", 1), ("/b.mp4", 1)}
        assert sessions[0].songs_by_singer["Bob"] == [("/c.mp4", 1)]

    def test_songs_by_singer_counts_repeats(self):
        events = [
            _event("/a.mp4", "Alice", "2026-01-01 20:00:00"),
            _event("/a.mp4", "Alice", "2026-01-01 20:05:00"),
        ]
        sessions = compute_all_sessions(events)
        assert sessions[0].songs_by_singer["Alice"] == [("/a.mp4", 2)]

    def test_songs_by_singer_excludes_blank_users(self):
        events = [_event("/a.mp4", "", "2026-01-01 20:00:00")]
        sessions = compute_all_sessions(events)
        assert sessions[0].songs_by_singer == {}

    def test_name_defaults_to_none(self):
        events = [_event("/a.mp4", "Alice", "2026-01-01 20:00:00")]
        sessions = compute_all_sessions(events)
        assert sessions[0].name is None

    def test_name_attached_by_matching_started_at(self):
        events = [
            _event("/old.mp4", "Alice", "2026-01-01 10:00:00"),
            _event("/new.mp4", "Bob", "2026-01-05 10:00:00"),
        ]
        names = {"2026-01-01 10:00:00": "John's Birthday"}
        sessions = compute_all_sessions(events, gap_hours=1.0, names=names)
        assert sessions[0].name == "John's Birthday"
        assert sessions[1].name is None


class TestIsSessionLive:
    def test_live_when_last_play_within_gap(self):
        session = compute_all_sessions(
            [_event("/a.mp4", "Alice", "2026-01-01 20:00:00")], gap_hours=1.0
        )[0]
        now = datetime(2026, 1, 1, 20, 30, 0)
        assert is_session_live(session, now=now, gap_hours=1.0) is True

    def test_not_live_after_gap_elapses(self):
        session = compute_all_sessions(
            [_event("/a.mp4", "Alice", "2026-01-01 20:00:00")], gap_hours=1.0
        )[0]
        now = datetime(2026, 1, 1, 22, 0, 0)
        assert is_session_live(session, now=now, gap_hours=1.0) is False


class TestSessionsCache:
    """Recap is loaded by every guest and polled by the splash, so the derivation
    is memoised. It must still notice new plays and renamed sessions."""

    @pytest.fixture(autouse=True)
    def _clear(self):
        clear_sessions_cache()
        yield
        clear_sessions_cache()

    @pytest.fixture
    def db(self, tmp_path):
        d = KaraokeDatabase(str(tmp_path / "cache.db"))
        yield d
        d.close()

    def test_returns_sessions(self, db):
        db.record_play("/songs/a.mp4", "Alex")
        sessions = get_sessions(db)
        assert len(sessions) == 1
        assert sessions[0].play_count == 1

    def test_second_call_does_not_reread_history(self, db):
        db.record_play("/songs/a.mp4", "Alex")
        get_sessions(db)

        with patch.object(db, "get_all_play_events", wraps=db.get_all_play_events) as spy:
            get_sessions(db)
            spy.assert_not_called()

    def test_a_new_play_invalidates_the_cache(self, db):
        db.record_play("/songs/a.mp4", "Alex")
        assert get_sessions(db)[0].play_count == 1

        db.record_play("/songs/b.mp4", "Sam")

        assert get_sessions(db)[0].play_count == 2

    def test_renaming_a_session_invalidates_the_cache(self, db):
        db.record_play("/songs/a.mp4", "Alex")
        started = get_sessions(db)[0].started_at
        assert get_sessions(db)[0].name is None

        db.set_session_name(started, "Birthday")

        assert get_sessions(db)[0].name == "Birthday"

    def test_marker_is_stable_when_nothing_changes(self, db):
        db.record_play("/songs/a.mp4", "Alex")
        assert db.get_play_events_marker() == db.get_play_events_marker()

    def test_marker_advances_on_a_new_play(self, db):
        db.record_play("/songs/a.mp4", "Alex")
        before = db.get_play_events_marker()
        db.record_play("/songs/b.mp4", "Sam")
        assert db.get_play_events_marker() > before

    def test_marker_on_empty_history(self, db):
        assert db.get_play_events_marker() == 0
