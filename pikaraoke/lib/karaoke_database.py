"""SQLite database layer for persistent song library storage."""

import os
import sqlite3
import threading

from pikaraoke.lib.get_platform import get_data_directory

_SCHEMA = """
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS songs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT UNIQUE NOT NULL,
    youtube_id TEXT,
    format TEXT NOT NULL,
    artist TEXT,
    title TEXT,
    variant TEXT,
    year INTEGER,
    genre TEXT,
    metadata_status TEXT DEFAULT 'pending',
    enrichment_attempts INTEGER DEFAULT 0,
    last_enrichment_attempt TEXT,
    play_count INTEGER NOT NULL DEFAULT 0,
    last_played_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_youtube_id ON songs(youtube_id);
CREATE INDEX IF NOT EXISTS idx_artist ON songs(artist);
CREATE INDEX IF NOT EXISTS idx_title ON songs(title);
CREATE INDEX IF NOT EXISTS idx_metadata_status ON songs(metadata_status);

CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS play_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    user TEXT,
    device_id TEXT,
    played_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_play_events_played_at ON play_events(played_at);

CREATE TABLE IF NOT EXISTS session_names (
    started_at TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

-- One row per browser that has ever queued a song. `name` is the display
-- name that device is currently using; play_events keeps the name as it was
-- at the time, so renaming yourself doesn't rewrite history.
CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY,
    name TEXT,
    first_seen TEXT DEFAULT CURRENT_TIMESTAMP,
    last_seen TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


class KaraokeDatabase:
    """Persistent song library backed by SQLite.

    Pure data layer with no filesystem operations. All paths are stored as
    native OS strings (str(path), never as_posix()).
    """

    def __init__(self, db_path: str | None = None) -> None:
        if db_path is None:
            db_path = os.path.join(get_data_directory(), "pikaraoke.db")
        self._db_path = db_path
        # All operations (including reads) share a single connection, so the
        # lock is required for thread safety -- Python's sqlite3.Connection is
        # not thread-safe even with check_same_thread=False. WAL mode benefits
        # crash recovery and write performance; Python-level read concurrency
        # would require separate connections per reader.
        self._lock = threading.Lock()
        self._conn = self._connect()
        self._create_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _create_schema(self) -> None:
        self._conn.executescript(_SCHEMA)
        with self._conn:
            self._conn.execute("PRAGMA user_version = 1")
        self._migrate_schema()

    def _migrate_schema(self) -> None:
        """Add columns introduced after a database may already exist on disk."""
        columns = {row[1] for row in self._conn.execute("PRAGMA table_info(songs)")}
        with self._conn:
            if "play_count" not in columns:
                self._conn.execute(
                    "ALTER TABLE songs ADD COLUMN play_count INTEGER NOT NULL DEFAULT 0"
                )
            if "last_played_at" not in columns:
                self._conn.execute("ALTER TABLE songs ADD COLUMN last_played_at TEXT")

        # Plays recorded before device tracking existed keep a NULL device_id --
        # they can't be attributed retroactively, so per-device stats start here.
        play_event_columns = {
            row[1] for row in self._conn.execute("PRAGMA table_info(play_events)")
        }
        if "device_id" not in play_event_columns:
            with self._conn:
                self._conn.execute("ALTER TABLE play_events ADD COLUMN device_id TEXT")

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_all_song_paths(self) -> list[str]:
        """Return all song file paths (unsorted; SongList handles sort order)."""
        with self._lock:
            rows = self._conn.execute("SELECT file_path FROM songs").fetchall()
            return [row[0] for row in rows]

    def get_song_count(self) -> int:
        """Return the total number of songs in the library."""
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0]

    def get_format(self, file_path: str) -> str | None:
        """Return the format string for a song, or None if not found."""
        with self._lock:
            row = self._conn.execute(
                "SELECT format FROM songs WHERE file_path = ?", (file_path,)
            ).fetchone()
            return row[0] if row else None

    def get_play_counts(self) -> dict[str, int]:
        """Return a map of file_path -> play_count for every song in the library."""
        with self._lock:
            rows = self._conn.execute("SELECT file_path, play_count FROM songs").fetchall()
            return {row["file_path"]: row["play_count"] for row in rows}

    def get_top_songs(self, limit: int = 10) -> list[dict]:
        """Return the most-played songs, highest play_count first.

        Songs that have never been played (play_count = 0) are excluded.
        """
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT file_path, artist, title, variant, play_count, last_played_at
                FROM songs
                WHERE play_count > 0
                ORDER BY play_count DESC, last_played_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Batch write operations (used by LibraryScanner)
    # ------------------------------------------------------------------

    def insert_songs(self, songs: list[dict]) -> None:
        """Batch-insert song records. Silently ignores duplicate file_paths."""
        with self._lock, self._conn:
            self._conn.executemany(
                """
                INSERT OR IGNORE INTO songs (file_path, youtube_id, format)
                VALUES (:file_path, :youtube_id, :format)
                """,
                songs,
            )

    def update_paths(self, moves: list[tuple[str, str]]) -> None:
        """Batch-update file paths for moved songs.

        Args:
            moves: List of (old_path, new_path) tuples.
        """
        with self._lock, self._conn:
            self._conn.executemany(
                "UPDATE songs SET file_path = ?, updated_at = CURRENT_TIMESTAMP WHERE file_path = ?",
                [(new, old) for old, new in moves],
            )

    def delete_by_paths(self, file_paths: list[str]) -> None:
        """Batch-delete songs by file path."""
        with self._lock, self._conn:
            self._conn.executemany(
                "DELETE FROM songs WHERE file_path = ?",
                [(p,) for p in file_paths],
            )

    def apply_scan_diff(
        self,
        moves: list[tuple[str, str]],
        inserts: list[dict],
        deletes: list[str],
    ) -> None:
        """Apply a complete scan diff atomically in a single transaction."""
        with self._lock, self._conn:
            if moves:
                self._conn.executemany(
                    "UPDATE songs SET file_path = ?, updated_at = CURRENT_TIMESTAMP WHERE file_path = ?",
                    [(new, old) for old, new in moves],
                )
            if inserts:
                self._conn.executemany(
                    """
                    INSERT OR IGNORE INTO songs (file_path, youtube_id, format)
                    VALUES (:file_path, :youtube_id, :format)
                    """,
                    inserts,
                )
            if deletes:
                self._conn.executemany(
                    "DELETE FROM songs WHERE file_path = ?",
                    [(p,) for p in deletes],
                )

    # ------------------------------------------------------------------
    # Single-record write operations (delegate to batch methods)
    # ------------------------------------------------------------------

    def delete_by_path(self, file_path: str) -> None:
        """Delete a single song by file path (UI-triggered delete)."""
        self.delete_by_paths([file_path])

    def update_path(self, old_path: str, new_path: str) -> None:
        """Update a single song's file path (UI-triggered rename)."""
        self.update_paths([(old_path, new_path)])

    def record_play(self, file_path: str, user: str, device_id: str = "") -> None:
        """Record a play: bumps the song's lifetime count and logs a play event.

        The lifetime count update is a no-op if the path isn't in the library,
        but the event is still logged -- it's a historical record of what was
        played, independent of whether the song is still in the library.
        """
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE songs
                SET play_count = play_count + 1, last_played_at = CURRENT_TIMESTAMP
                WHERE file_path = ?
                """,
                (file_path,),
            )
            self._conn.execute(
                "INSERT INTO play_events (file_path, user, device_id) VALUES (?, ?, ?)",
                (file_path, user, device_id or None),
            )

    def record_device(self, device_id: str, name: str) -> None:
        """Remember a device and the display name it's currently using."""
        if not device_id:
            return
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO devices (device_id, name) VALUES (?, ?)
                ON CONFLICT(device_id) DO UPDATE
                SET name = excluded.name, last_seen = CURRENT_TIMESTAMP
                """,
                (device_id, name),
            )

    def get_device_stats(self) -> list[dict]:
        """Lifetime per-device totals, most songs first.

        Only covers plays recorded since device tracking was added; older
        play_events have no device_id and are excluded.
        """
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT d.device_id, d.name, d.first_seen, d.last_seen,
                       COUNT(p.id) AS play_count,
                       COUNT(DISTINCT p.user) AS name_count
                FROM devices d
                LEFT JOIN play_events p ON p.device_id = d.device_id
                GROUP BY d.device_id
                ORDER BY play_count DESC, d.last_seen DESC
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def get_all_play_events(self) -> list[dict]:
        """Return the full play event history, oldest first.

        Never pruned -- this is the source of truth sessions are derived
        from, so history stays reconstructable indefinitely.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT file_path, user, device_id, played_at FROM play_events "
                "ORDER BY played_at ASC"
            ).fetchall()
            return [dict(row) for row in rows]

    def get_session_names(self) -> dict[str, str]:
        """Return a map of session started_at -> admin-given name."""
        with self._lock:
            rows = self._conn.execute("SELECT started_at, name FROM session_names").fetchall()
            return {row["started_at"]: row["name"] for row in rows}

    def set_session_name(self, started_at: str, name: str) -> None:
        """Set (or clear, if `name` is blank) the admin-given name for a session."""
        with self._lock, self._conn:
            if name.strip():
                self._conn.execute(
                    "INSERT OR REPLACE INTO session_names (started_at, name) VALUES (?, ?)",
                    (started_at, name.strip()),
                )
            else:
                self._conn.execute("DELETE FROM session_names WHERE started_at = ?", (started_at,))

    # ------------------------------------------------------------------
    # Metadata (app-level key-value store)
    # ------------------------------------------------------------------

    def get_metadata(self, key: str) -> str | None:
        """Return the value for a metadata key, or None if not set."""
        with self._lock:
            row = self._conn.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
            return row[0] if row else None

    def set_metadata(self, key: str, value: str) -> None:
        """Set a metadata key-value pair (upsert)."""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                (key, value),
            )

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def check_integrity(self) -> tuple[bool, str]:
        """Run PRAGMA integrity_check. Returns (ok, message)."""
        with self._lock:
            result = self._conn.execute("PRAGMA integrity_check").fetchone()[0]
            return result == "ok", result

    def close(self) -> None:
        """Close the database connection."""
        with self._lock:
            self._conn.close()
