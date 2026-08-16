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

An admin can pin a device as the preferred master. The pin is keyed on the
device cookie rather than the socket id, so the chosen TV reclaims the role
across reconnects, restarts and new sockets -- which is what stops it coming
back as a slave against its own corpse after a dropped connection.
"""

import time
from dataclasses import dataclass, field

# How long a master may go unheard before another screen may take over.
# Generous on purpose: a brief network hiccup shouldn't cost the role,
# because handing it to another screen mid-song is more disruptive than
# waiting out a blip.
MASTER_STALE_SECONDS = 30.0


@dataclass
class SplashScreen:
    """A connected splash screen, as shown on the admin page."""

    sid: str
    device_id: str = ""
    ip_address: str = ""
    connected_at: float = 0.0
    last_seen: float = field(default=0.0)


class SplashRegistry:
    """Which splash screens are connected, and which one is master."""

    def __init__(self, stale_after: float = MASTER_STALE_SECONDS) -> None:
        self._stale_after = stale_after
        self._screens: dict[str, SplashScreen] = {}
        self._master: str | None = None
        self._pinned_device: str = ""

    @property
    def master(self) -> str | None:
        """The sid currently allowed to drive playback."""
        return self._master

    @property
    def connections(self) -> set[str]:
        """Every splash sid currently registered."""
        return set(self._screens)

    @property
    def pinned_device(self) -> str:
        """The device chosen by an admin to hold the master role, if any."""
        return self._pinned_device

    def screens(self) -> list[SplashScreen]:
        """Connected screens, oldest connection first."""
        return sorted(self._screens.values(), key=lambda s: s.connected_at)

    def register(
        self,
        sid: str,
        device_id: str = "",
        ip_address: str = "",
        now: float | None = None,
    ) -> str:
        """Add a splash screen, returning the role it should adopt.

        Takes the master role when pinned to this device, when there's no
        master, or when the incumbent has gone quiet long enough to presume
        it's gone.
        """
        now = self._clock(now)
        self._screens[sid] = SplashScreen(
            sid=sid,
            device_id=device_id,
            ip_address=ip_address,
            connected_at=now,
            last_seen=now,
        )

        if self._is_pinned(sid) or self._master is None or self._is_stale(self._master, now):
            self._master = sid
        return "master" if self._master == sid else "slave"

    def touch(self, sid: str, now: float | None = None) -> None:
        """Record that a screen is still alive. Ignores unknown sids."""
        screen = self._screens.get(sid)
        if screen:
            screen.last_seen = self._clock(now)

    def remove(self, sid: str, now: float | None = None) -> str | None:
        """Drop a screen on disconnect.

        Returns the newly promoted master's sid when the role moved, so the
        caller can tell that screen about it. Returns None otherwise.
        """
        self._screens.pop(sid, None)
        if sid != self._master:
            return None

        self._master = None
        return self._elect()

    def is_master(self, sid: str) -> bool:
        """Whether this screen is allowed to drive playback."""
        return sid == self._master

    def pin_device(self, device_id: str) -> str | None:
        """Pin a device as preferred master, promoting it if it's connected.

        Returns the sid that took the role, or None if the device isn't
        currently connected -- it will claim the role when it registers.
        """
        self._pinned_device = device_id or ""
        if not self._pinned_device:
            return None

        for screen in self.screens():
            if screen.device_id == self._pinned_device:
                self._master = screen.sid
                return screen.sid
        return None

    def demote_stale_master(self, now: float | None = None) -> str | None:
        """Replace a master that has gone quiet, if another screen can take over.

        Deliberately a no-op when no replacement exists: stripping the only
        screen of the role during a network blip would achieve nothing and
        leave nobody able to end the current song.

        Returns the newly promoted sid, or None if nothing changed.
        """
        now = self._clock(now)
        if self._master is None or not self._is_stale(self._master, now):
            return None
        if len(self._screens) < 2:
            return None

        stale = self._master
        self._master = None
        new_master = self._elect(exclude=stale)
        if new_master is None:
            # Nothing better available; leave the incumbent alone.
            self._master = stale
        return new_master

    def _elect(self, exclude: str | None = None) -> str | None:
        """Promote whichever remaining screen was heard from most recently."""
        candidates = {sid: s.last_seen for sid, s in self._screens.items() if sid != exclude}
        if not candidates:
            return None
        # A pinned device always outranks recency.
        for sid in candidates:
            if self._is_pinned(sid):
                self._master = sid
                return sid
        self._master = max(candidates, key=candidates.__getitem__)
        return self._master

    def _is_pinned(self, sid: str) -> bool:
        screen = self._screens.get(sid)
        return (
            bool(self._pinned_device) and bool(screen) and screen.device_id == self._pinned_device
        )

    def _is_stale(self, sid: str, now: float) -> bool:
        """Whether a screen has gone quiet long enough to presume it's gone.

        Only meaningful for the master: it reports position while a song
        plays, whereas slaves send nothing after registering and so always
        look quiet. That's why staleness is consulted when deciding whether
        to *replace* the master, and never to evict a screen.
        """
        screen = self._screens.get(sid)
        return screen is None or now - screen.last_seen > self._stale_after

    @staticmethod
    def _clock(now: float | None) -> float:
        # Monotonic: election must not be skewed by wall-clock adjustments.
        return time.monotonic() if now is None else now
