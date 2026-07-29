"""Persisted list of IP addresses flagged as bots (e.g. by the honeypot trap).

Once an IP is blocked, party-disrupting actions (queue/playback) from it are
silently no-op'd rather than rejected with an error, so an automated scraper
gets no signal that anything changed.
"""

import os
import sqlite3
import threading

from pikaraoke.lib.get_platform import get_data_directory

_SCHEMA = """
CREATE TABLE IF NOT EXISTS blocked_ips (
    ip_address TEXT PRIMARY KEY,
    blocked_at TEXT DEFAULT CURRENT_TIMESTAMP,
    reason TEXT
);
"""


class IPBlocklist:
    """Tracks IPs flagged as bots. Small and admin-manageable, not auto-expiring."""

    def __init__(self, db_path: str | None = None) -> None:
        if db_path is None:
            db_path = os.path.join(get_data_directory(), "ip_blocklist.db")
        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def block(self, ip_address: str, reason: str = "") -> None:
        """Flag an IP. Safe to call repeatedly for the same IP."""
        if not ip_address:
            return
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO blocked_ips (ip_address, reason) VALUES (?, ?)",
                (ip_address, reason),
            )

    def unblock(self, ip_address: str) -> None:
        """Remove an IP from the blocklist."""
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM blocked_ips WHERE ip_address = ?", (ip_address,))

    def is_blocked(self, ip_address: str) -> bool:
        """Check whether an IP is currently flagged."""
        if not ip_address:
            return False
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM blocked_ips WHERE ip_address = ?", (ip_address,)
            ).fetchone()
            return row is not None

    def get_all(self) -> list[dict]:
        """Return all blocked IPs, most recently blocked first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT ip_address, blocked_at, reason FROM blocked_ips ORDER BY blocked_at DESC"
            ).fetchall()
            return [dict(row) for row in rows]

    def close(self) -> None:
        """Close the database connection."""
        with self._lock:
            self._conn.close()
