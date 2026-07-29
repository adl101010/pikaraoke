"""Computes karaoke session stats from the play event log.

Sessions are never stored -- they're derived on read from the full history
of play_events. A session is a run of plays with no gap longer than
GAP_HOURS between consecutive plays. This means the current session is
always live (it keeps growing while the party is still going) and past
sessions can always be reconstructed exactly, since the raw event log is
never pruned.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

GAP_HOURS = 1.0


@dataclass
class SessionRecap:
    """Summary of a single karaoke session (current or past)."""

    play_count: int
    singer_count: int
    started_at: str
    ended_at: str
    top_songs: list[tuple[str, int]]
    top_singers: list[tuple[str, int]]


def _summarize(session_events: list[dict]) -> SessionRecap:
    song_counts = Counter(e["file_path"] for e in session_events)
    singer_counts = Counter(e["user"] for e in session_events if e["user"])
    return SessionRecap(
        play_count=len(session_events),
        singer_count=len(singer_counts),
        started_at=session_events[0]["played_at"],
        ended_at=session_events[-1]["played_at"],
        top_songs=song_counts.most_common(10),
        top_singers=singer_counts.most_common(10),
    )


def compute_all_sessions(events: list[dict], gap_hours: float = GAP_HOURS) -> list[SessionRecap]:
    """Split the full play history into sessions, oldest first.

    Args:
        events: Play events sorted oldest-first, each with file_path, user,
            and played_at (a sqlite CURRENT_TIMESTAMP-formatted string).
        gap_hours: A session ends wherever the gap between two consecutive
            plays exceeds this many hours.
    """
    if not events:
        return []

    gap = timedelta(hours=gap_hours)
    sessions = []
    batch = [events[0]]
    for prev, curr in zip(events, events[1:]):
        prev_time = datetime.fromisoformat(prev["played_at"])
        curr_time = datetime.fromisoformat(curr["played_at"])
        if curr_time - prev_time > gap:
            sessions.append(_summarize(batch))
            batch = []
        batch.append(curr)
    sessions.append(_summarize(batch))
    return sessions


def is_session_live(
    session: SessionRecap, now: datetime | None = None, gap_hours: float = GAP_HOURS
) -> bool:
    """Whether a session is still ongoing (no long-enough gap has closed it out yet)."""
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    ended = datetime.fromisoformat(session.ended_at)
    return now - ended <= timedelta(hours=gap_hours)
