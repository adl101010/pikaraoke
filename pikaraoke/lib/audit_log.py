"""SQLite-backed audit log of admin/queue/playback actions.

Bounded by design: every write prunes anything beyond the most recent
MAX_ENTRIES rows, so the table can never grow unbounded.
"""

import os
import sqlite3
import threading

from pikaraoke.lib.get_platform import get_data_directory

MAX_ENTRIES = 2000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
    user TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT,
    ip_address TEXT,
    device_id TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_log_id ON audit_log(id DESC);
"""


class AuditLog:
    """Records who did what, capped at the most recent MAX_ENTRIES entries."""

    def __init__(self, db_path: str | None = None) -> None:
        if db_path is None:
            db_path = os.path.join(get_data_directory(), "audit_log.db")
        self._db_path = db_path
        # Single shared connection; sqlite3.Connection isn't thread-safe even
        # with check_same_thread=False, so all access goes through the lock.
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._migrate_schema()

    def _migrate_schema(self) -> None:
        """Add columns introduced after a database may already exist on disk."""
        columns = {row[1] for row in self._conn.execute("PRAGMA table_info(audit_log)")}
        with self._conn:
            if "ip_address" not in columns:
                self._conn.execute("ALTER TABLE audit_log ADD COLUMN ip_address TEXT")
            if "device_id" not in columns:
                self._conn.execute("ALTER TABLE audit_log ADD COLUMN device_id TEXT")

    def record(
        self,
        user: str,
        action: str,
        detail: str = "",
        ip_address: str = "",
        device_id: str = "",
    ) -> None:
        """Add an entry and prune anything beyond the most recent MAX_ENTRIES."""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO audit_log (user, action, detail, ip_address, device_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (user or "Unknown", action, detail, ip_address or "Unknown", device_id or None),
            )
            self._conn.execute(
                "DELETE FROM audit_log WHERE id NOT IN "
                "(SELECT id FROM audit_log ORDER BY id DESC LIMIT ?)",
                (MAX_ENTRIES,),
            )

    def get_recent(self, limit: int = 100) -> list[dict]:
        """Return the most recent entries, newest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT timestamp, user, action, detail, ip_address, device_id FROM audit_log "
                "ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def close(self) -> None:
        """Close the database connection."""
        with self._lock:
            self._conn.close()
