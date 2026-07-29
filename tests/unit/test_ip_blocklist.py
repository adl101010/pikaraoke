"""Tests for the persisted honeypot IP blocklist."""

import os

import pytest

from pikaraoke.lib.ip_blocklist import IPBlocklist


@pytest.fixture
def blocklist(tmp_path):
    bl = IPBlocklist(db_path=str(tmp_path / "ip_blocklist.db"))
    yield bl
    bl.close()


def test_block_and_is_blocked(blocklist):
    assert blocklist.is_blocked("10.0.0.5") is False

    blocklist.block("10.0.0.5", "Followed honeypot")

    assert blocklist.is_blocked("10.0.0.5") is True


def test_unblock_removes_entry(blocklist):
    blocklist.block("10.0.0.5", "Followed honeypot")
    assert blocklist.is_blocked("10.0.0.5") is True

    blocklist.unblock("10.0.0.5")

    assert blocklist.is_blocked("10.0.0.5") is False


def test_blocking_same_ip_twice_is_safe(blocklist):
    blocklist.block("10.0.0.5", "First reason")
    blocklist.block("10.0.0.5", "Second reason")

    entries = blocklist.get_all()
    assert len(entries) == 1


def test_blocking_empty_ip_is_a_no_op(blocklist):
    blocklist.block("", "reason")
    blocklist.block(None, "reason")

    assert blocklist.get_all() == []


def test_is_blocked_with_empty_ip_returns_false(blocklist):
    assert blocklist.is_blocked("") is False
    assert blocklist.is_blocked(None) is False


def test_get_all_returns_ip_and_reason(blocklist):
    blocklist.block("10.0.0.5", "Followed honeypot")

    entries = blocklist.get_all()

    assert len(entries) == 1
    assert entries[0]["ip_address"] == "10.0.0.5"
    assert entries[0]["reason"] == "Followed honeypot"
    assert entries[0]["blocked_at"]


def test_db_file_created_in_given_path(tmp_path):
    db_path = str(tmp_path / "ip_blocklist.db")
    bl = IPBlocklist(db_path=db_path)
    bl.block("10.0.0.5")
    bl.close()

    assert os.path.isfile(db_path)
