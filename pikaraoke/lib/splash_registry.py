"""Tracks connected splash screens and which one drives playback.

One splash screen is elected master: only it may end the current song or
report playback position, so a second screen can't cut a song short or fight
over the timeline.

Election is driven by liveness rather than by Socket.IO's disconnect event
alone. A screen that vanishes without a clean close -- tab killed, network
dropped, a close frame mangled by a proxy -- isn't reaped for up to ~45s at
the default ping timeouts. Until then the dead sid would keep the role and
every screen opened after it would be made a slave, leaving nobody to drive
playback.
"""

import time

# How long a master may go unheard before a newly arriving screen may take
# over. Generous on purpose: a brief network hiccup shouldn't cost the role,
# because handing it to another screen mid-song is more disruptive than
# waiting out a blip.
MASTER_STALE_SECONDS = 30.0


class SplashRegistry:
    """Which splash screens are connected, and which one is master."""

    def __init__(self, stale_after: float = MASTER_STALE_SECONDS) -> None:
        self._stale_after = stale_after
        self._last_seen: dict[str, float] = {}
        self._master: str | None = None

    @property
    def master(self) -> str | None:
        """The sid currently allowed to drive playback."""
        return self._master

    @property
    def connections(self) -> set[str]:
        """Every splash sid currently registered."""
        return set(self._last_seen)

    def register(self, sid: str, now: float | None = None) -> str:
        """Add a splash screen, returning the role it should adopt.

        Takes over as master if there isn't one, or if the incumbent has gone
        quiet long enough to be presumed gone.
        """
        now = self._clock(now)
        self._last_seen[sid] = now
        if self._master is None or self._is_stale(self._master, now):
            self._master = sid
        return "master" if self._master == sid else "slave"

    def touch(self, sid: str, now: float | None = None) -> None:
        """Record that a screen is still alive. Ignores unknown sids."""
        if sid in self._last_seen:
            self._last_seen[sid] = self._clock(now)

    def remove(self, sid: str, now: float | None = None) -> str | None:
        """Drop a screen on disconnect.

        Returns the newly promoted master's sid when the role moved, so the
        caller can tell that screen about it. Returns None otherwise.
        """
        self._last_seen.pop(sid, None)
        if sid != self._master:
            return None

        self._master = None
        if not self._last_seen:
            return None

        # Prefer whichever survivor was heard from most recently.
        self._master = max(self._last_seen, key=self._last_seen.__getitem__)
        return self._master

    def is_master(self, sid: str) -> bool:
        """Whether this screen is allowed to drive playback."""
        return sid == self._master

    def _is_stale(self, sid: str, now: float) -> bool:
        """Whether a screen has gone quiet long enough to presume it's gone.

        Only meaningful for the master: it reports position while a song
        plays, whereas slaves send nothing after registering and so always
        look quiet. That's why staleness is consulted when deciding whether
        to *replace* the master, and never to evict a screen.
        """
        return now - self._last_seen.get(sid, 0.0) > self._stale_after

    @staticmethod
    def _clock(now: float | None) -> float:
        # Monotonic: election must not be skewed by wall-clock adjustments.
        return time.monotonic() if now is None else now
