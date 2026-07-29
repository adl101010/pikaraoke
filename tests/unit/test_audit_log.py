"""Tests for the SQLite-backed audit log, including its pruning behavior."""

import os
import sqlite3

import pytest

from pikaraoke.lib.audit_log import AuditLog


@pytest.fixture
def audit_log(tmp_path):
    log = AuditLog(db_path=str(tmp_path / "audit_log.db"))
    yield log
    log.close()


def test_record_and_get_recent(audit_log):
    audit_log.record("Alice", "Queued song", "Bohemian Rhapsody", "10.0.0.5")
    audit_log.record("Bob", "Paused playback")

    entries = audit_log.get_recent()

    assert len(entries) == 2
    # Newest first.
    assert entries[0]["user"] == "Bob"
    assert entries[0]["action"] == "Paused playback"
    assert entries[0]["detail"] == ""
    assert entries[0]["ip_address"] == "Unknown"
    assert entries[1]["user"] == "Alice"
    assert entries[1]["detail"] == "Bohemian Rhapsody"
    assert entries[1]["ip_address"] == "10.0.0.5"
    assert entries[1]["timestamp"]


def test_missing_user_defaults_to_unknown(audit_log):
    audit_log.record("", "Skipped song")
    audit_log.record(None, "Skipped song")

    entries = audit_log.get_recent()

    assert entries[0]["user"] == "Unknown"
    assert entries[1]["user"] == "Unknown"


def test_missing_ip_defaults_to_unknown(audit_log):
    audit_log.record("Alice", "Skipped song")

    entries = audit_log.get_recent()

    assert entries[0]["ip_address"] == "Unknown"


def test_migrates_database_missing_ip_address_column(tmp_path):
    """A database created before ip_address existed should gain the column, not break."""
    db_path = str(tmp_path / "audit_log.db")

    # Simulate the old (pre-ip_address) schema on disk.
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
            user TEXT NOT NULL,
            action TEXT NOT NULL,
            detail TEXT
        );
        """
    )
    conn.execute(
        "INSERT INTO audit_log (user, action, detail) VALUES (?, ?, ?)",
        ("Alice", "Queued song", "Old Entry"),
    )
    conn.commit()
    conn.close()

    log = AuditLog(db_path=db_path)
    try:
        log.record("Bob", "Paused playback", "", "10.0.0.9")
        entries = log.get_recent()

        assert len(entries) == 2
        # New entry has an IP; the pre-migration row just has no value for it.
        assert entries[0]["ip_address"] == "10.0.0.9"
        assert entries[1]["ip_address"] is None
    finally:
        log.close()


def test_get_recent_respects_limit(audit_log):
    for i in range(10):
        audit_log.record("User", f"Action {i}")

    entries = audit_log.get_recent(limit=3)

    assert len(entries) == 3
    # Newest first: last recorded action is "Action 9".
    assert entries[0]["action"] == "Action 9"


def test_prunes_beyond_max_entries(tmp_path):
    log = AuditLog(db_path=str(tmp_path / "audit_log.db"))
    max_entries = 5
    # Shrink the cap for a fast test instead of writing 2000 real rows.
    import pikaraoke.lib.audit_log as audit_log_module

    original_max = audit_log_module.MAX_ENTRIES
    audit_log_module.MAX_ENTRIES = max_entries
    try:
        for i in range(max_entries + 3):
            log.record("User", f"Action {i}")

        entries = log.get_recent(limit=100)

        assert len(entries) == max_entries
        # Only the most recent max_entries survive.
        assert entries[0]["action"] == f"Action {max_entries + 2}"
        assert entries[-1]["action"] == "Action 3"
    finally:
        audit_log_module.MAX_ENTRIES = original_max
        log.close()


def test_db_file_created_in_given_path(tmp_path):
    db_path = str(tmp_path / "audit_log.db")
    log = AuditLog(db_path=db_path)
    log.record("Alice", "Queued song")
    log.close()

    assert os.path.isfile(db_path)
