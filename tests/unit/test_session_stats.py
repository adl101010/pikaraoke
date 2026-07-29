"""Unit tests for session_stats (session-history computation)."""

from datetime import datetime

from pikaraoke.lib.session_stats import compute_all_sessions, is_session_live


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
