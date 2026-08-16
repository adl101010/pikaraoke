"""Tests for the socket broadcasts driven by controller actions."""

from unittest.mock import MagicMock

import pytest

from pikaraoke.routes import socket_events


@pytest.fixture
def socketio(monkeypatch):
    """Swap in a mock for the module-level SocketIO the broadcasts use."""
    mock = MagicMock()
    monkeypatch.setattr(socket_events, "_socketio", mock)
    return mock


class TestBroadcastSeek:
    def test_reaches_every_client_not_just_the_splash_room(self, socketio):
        """Controllers need it too: a second admin's scrubber follows this.

        Restricting it to the splash room left other admins showing the old
        position until the song changed.
        """
        socket_events.broadcast_seek(42)

        socketio.emit.assert_called_once_with("seek", 42)
        _, kwargs = socketio.emit.call_args
        assert "room" not in kwargs

    def test_is_a_no_op_before_socketio_is_wired_up(self, monkeypatch):
        monkeypatch.setattr(socket_events, "_socketio", None)

        socket_events.broadcast_seek(42)  # must not raise
