"""Tests for playback controller routes: admin gating, audit logging, and
the honeypot/no-identity blocking of pause/skip/transpose/volume."""

from unittest.mock import MagicMock, patch

import pytest
import werkzeug
from flask import Flask

if not hasattr(werkzeug, "__version__"):
    werkzeug.__version__ = "3.0.0"

from pikaraoke.routes.controller import controller_bp
from pikaraoke.routes.home import home_bp


@pytest.fixture
def app():
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(controller_bp)
    app.register_blueprint(home_bp)
    app.extensions["babel"] = MagicMock()
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def _unblocked_karaoke():
    """A MagicMock karaoke instance with the block check passing through."""
    k = MagicMock()
    k.ip_blocklist.is_blocked.return_value = False
    return k


class TestSkipRoute:
    """Admins skip anyone's song; everyone else only their own."""

    @patch("pikaraoke.routes.controller.is_admin", return_value=False)
    @patch("pikaraoke.routes.controller.get_karaoke_instance")
    @patch("pikaraoke.routes.controller.broadcast_event")
    @patch("pikaraoke.routes.controller._", side_effect=lambda x: x)
    def test_non_admin_skip_is_blocked(
        self, mock_gettext, mock_broadcast, mock_get_instance, mock_is_admin, client
    ):
        mock_karaoke = MagicMock()
        mock_get_instance.return_value = mock_karaoke

        response = client.get("/skip")

        assert response.status_code == 302
        mock_karaoke.playback_controller.skip.assert_not_called()
        mock_karaoke.audit_log.record.assert_not_called()
        mock_broadcast.assert_not_called()

    @patch("pikaraoke.routes.controller.is_admin", return_value=True)
    @patch("pikaraoke.routes.controller.get_karaoke_instance")
    @patch("pikaraoke.routes.controller.broadcast_event")
    @patch("pikaraoke.routes.controller._", side_effect=lambda x: x)
    def test_admin_skip_still_works(
        self, mock_gettext, mock_broadcast, mock_get_instance, mock_is_admin, client
    ):
        mock_karaoke = MagicMock()
        mock_karaoke.playback_controller.now_playing = "Bohemian Rhapsody"
        mock_get_instance.return_value = mock_karaoke

        response = client.get("/skip?user=Alice")

        assert response.status_code == 302
        mock_karaoke.playback_controller.skip.assert_called_once()
        mock_broadcast.assert_called_once_with("skip", "user command")
        mock_karaoke.audit_log.record.assert_called_once_with(
            "Alice", "Skipped song", "Bohemian Rhapsody", "127.0.0.1"
        )

    @patch("pikaraoke.routes.controller.is_admin", return_value=False)
    @patch("pikaraoke.routes.controller.get_karaoke_instance")
    @patch("pikaraoke.routes.controller.broadcast_event")
    @patch("pikaraoke.routes.controller._", side_effect=lambda x: x)
    def test_non_admin_can_skip_own_song(
        self, mock_gettext, mock_broadcast, mock_get_instance, mock_is_admin, client
    ):
        mock_karaoke = _unblocked_karaoke()
        mock_karaoke.playback_controller.now_playing = "Bohemian Rhapsody"
        mock_karaoke.playback_controller.now_playing_user = "Alice"
        mock_get_instance.return_value = mock_karaoke

        response = client.get("/skip?user=Alice")

        assert response.status_code == 302
        mock_karaoke.playback_controller.skip.assert_called_once()
        mock_broadcast.assert_called_once_with("skip", "user command")
        mock_karaoke.audit_log.record.assert_called_once_with(
            "Alice", "Skipped own song", "Bohemian Rhapsody", "127.0.0.1"
        )

    @patch("pikaraoke.routes.controller.is_admin", return_value=False)
    @patch("pikaraoke.routes.controller.get_karaoke_instance")
    @patch("pikaraoke.routes.controller.broadcast_event")
    @patch("pikaraoke.routes.controller._", side_effect=lambda x: x)
    def test_own_song_match_ignores_case_and_whitespace(
        self, mock_gettext, mock_broadcast, mock_get_instance, mock_is_admin, client
    ):
        mock_karaoke = _unblocked_karaoke()
        mock_karaoke.playback_controller.now_playing_user = "Alice"
        mock_get_instance.return_value = mock_karaoke

        response = client.get("/skip?user=%20alice%20")

        assert response.status_code == 302
        mock_karaoke.playback_controller.skip.assert_called_once()

    @patch("pikaraoke.routes.controller.is_admin", return_value=False)
    @patch("pikaraoke.routes.controller.get_karaoke_instance")
    @patch("pikaraoke.routes.controller.broadcast_event")
    @patch("pikaraoke.routes.controller._", side_effect=lambda x: x)
    def test_non_admin_cannot_skip_someone_elses_song(
        self, mock_gettext, mock_broadcast, mock_get_instance, mock_is_admin, client
    ):
        mock_karaoke = _unblocked_karaoke()
        mock_karaoke.playback_controller.now_playing_user = "Bob"
        mock_get_instance.return_value = mock_karaoke

        response = client.get("/skip?user=Alice")

        assert response.status_code == 302
        mock_karaoke.playback_controller.skip.assert_not_called()
        mock_karaoke.audit_log.record.assert_not_called()
        mock_broadcast.assert_not_called()

    @patch("pikaraoke.routes.controller.is_admin", return_value=False)
    @patch("pikaraoke.routes.controller.get_karaoke_instance")
    @patch("pikaraoke.routes.controller.broadcast_event")
    @patch("pikaraoke.routes.controller._", side_effect=lambda x: x)
    def test_no_singer_on_current_song_denies_self_skip(
        self, mock_gettext, mock_broadcast, mock_get_instance, mock_is_admin, client
    ):
        mock_karaoke = _unblocked_karaoke()
        mock_karaoke.playback_controller.now_playing_user = ""
        mock_get_instance.return_value = mock_karaoke

        response = client.get("/skip?user=Alice")

        assert response.status_code == 302
        mock_karaoke.playback_controller.skip.assert_not_called()

    @patch("pikaraoke.routes.controller.is_admin", return_value=False)
    @patch("pikaraoke.routes.controller.get_karaoke_instance")
    @patch("pikaraoke.routes.controller.broadcast_event")
    @patch("pikaraoke.routes.controller._", side_effect=lambda x: x)
    def test_blocked_ip_cannot_self_skip(
        self, mock_gettext, mock_broadcast, mock_get_instance, mock_is_admin, client
    ):
        mock_karaoke = MagicMock()
        mock_karaoke.ip_blocklist.is_blocked.return_value = True
        mock_karaoke.playback_controller.now_playing_user = "Alice"
        mock_get_instance.return_value = mock_karaoke

        response = client.get("/skip?user=Alice")

        assert response.status_code == 302
        mock_karaoke.playback_controller.skip.assert_not_called()
        mock_karaoke.audit_log.record.assert_not_called()


class TestAuditLogging:
    """Pause/transpose/volume aren't admin-gated, but should still be logged."""

    @patch("pikaraoke.routes.controller.get_karaoke_instance")
    @patch("pikaraoke.routes.controller.broadcast_event")
    @patch("pikaraoke.routes.controller._", side_effect=lambda x: x)
    def test_pause_logs_paused_when_currently_playing(
        self, mock_gettext, mock_broadcast, mock_get_instance, client
    ):
        mock_karaoke = _unblocked_karaoke()
        mock_karaoke.playback_controller.is_paused = False
        mock_karaoke.playback_controller.now_playing = "Song A"
        mock_get_instance.return_value = mock_karaoke

        client.get("/pause?user=Bob")

        mock_karaoke.audit_log.record.assert_called_once_with(
            "Bob", "Paused playback", "Song A", "127.0.0.1"
        )

    @patch("pikaraoke.routes.controller.get_karaoke_instance")
    @patch("pikaraoke.routes.controller.broadcast_event")
    @patch("pikaraoke.routes.controller._", side_effect=lambda x: x)
    def test_pause_logs_resumed_when_currently_paused(
        self, mock_gettext, mock_broadcast, mock_get_instance, client
    ):
        mock_karaoke = _unblocked_karaoke()
        mock_karaoke.playback_controller.is_paused = True
        mock_karaoke.playback_controller.now_playing = "Song A"
        mock_get_instance.return_value = mock_karaoke

        client.get("/pause?user=Bob")

        mock_karaoke.audit_log.record.assert_called_once_with(
            "Bob", "Resumed playback", "Song A", "127.0.0.1"
        )

    @patch("pikaraoke.routes.controller.get_karaoke_instance")
    @patch("pikaraoke.routes.controller.broadcast_event")
    @patch("pikaraoke.routes.controller._", side_effect=lambda x: x)
    def test_transpose_logs_semitones_and_song(
        self, mock_gettext, mock_broadcast, mock_get_instance, client
    ):
        mock_karaoke = _unblocked_karaoke()
        mock_karaoke.playback_controller.now_playing = "Song A"
        mock_get_instance.return_value = mock_karaoke

        client.get("/transpose/3?user=Carol")

        mock_karaoke.audit_log.record.assert_called_once_with(
            "Carol", "Changed key", "3 semitones -- Song A", "127.0.0.1"
        )

    @patch("pikaraoke.routes.controller.get_karaoke_instance")
    @patch("pikaraoke.routes.controller.broadcast_event")
    @patch("pikaraoke.routes.controller._", side_effect=lambda x: x)
    def test_volume_logs_value(self, mock_gettext, mock_broadcast, mock_get_instance, client):
        mock_karaoke = _unblocked_karaoke()
        mock_get_instance.return_value = mock_karaoke

        client.get("/volume/0.5?user=Dana")

        mock_karaoke.audit_log.record.assert_called_once_with(
            "Dana", "Changed volume", "0.5", "127.0.0.1"
        )

    @patch("pikaraoke.routes.controller.get_karaoke_instance")
    @patch("pikaraoke.routes.controller.broadcast_event")
    @patch("pikaraoke.routes.controller._", side_effect=lambda x: x)
    def test_vol_up_logs(self, mock_gettext, mock_broadcast, mock_get_instance, client):
        mock_karaoke = _unblocked_karaoke()
        mock_get_instance.return_value = mock_karaoke

        client.get("/vol_up?user=Eve")

        mock_karaoke.audit_log.record.assert_called_once_with(
            "Eve", "Increased volume", "", "127.0.0.1"
        )

    @patch("pikaraoke.routes.controller.get_karaoke_instance")
    @patch("pikaraoke.routes.controller.broadcast_event")
    @patch("pikaraoke.routes.controller._", side_effect=lambda x: x)
    def test_vol_down_logs(self, mock_gettext, mock_broadcast, mock_get_instance, client):
        mock_karaoke = _unblocked_karaoke()
        mock_get_instance.return_value = mock_karaoke

        client.get("/vol_down?user=Eve")

        mock_karaoke.audit_log.record.assert_called_once_with(
            "Eve", "Decreased volume", "", "127.0.0.1"
        )

    @patch("pikaraoke.routes.controller.get_karaoke_instance")
    @patch("pikaraoke.routes.controller.broadcast_event")
    def test_restart_is_not_logged(self, mock_broadcast, mock_get_instance, client):
        """Restart wasn't in the requested list of logged actions."""
        mock_karaoke = MagicMock()
        mock_get_instance.return_value = mock_karaoke

        client.get("/restart")

        mock_karaoke.audit_log.record.assert_not_called()


class TestActionBlocking:
    """A blocked IP or a request with no user identity silently no-ops."""

    @patch("pikaraoke.routes.controller.get_karaoke_instance")
    @patch("pikaraoke.routes.controller.broadcast_event")
    def test_pause_without_user_param_is_blocked(self, mock_broadcast, mock_get_instance, client):
        mock_karaoke = _unblocked_karaoke()
        mock_karaoke.playback_controller.is_paused = False
        mock_get_instance.return_value = mock_karaoke

        response = client.get("/pause")

        assert response.status_code == 302
        mock_karaoke.playback_controller.pause.assert_not_called()
        mock_karaoke.audit_log.record.assert_not_called()
        mock_broadcast.assert_not_called()

    @patch("pikaraoke.routes.controller.get_karaoke_instance")
    @patch("pikaraoke.routes.controller.broadcast_event")
    def test_pause_with_whitespace_only_user_is_blocked(
        self, mock_broadcast, mock_get_instance, client
    ):
        mock_karaoke = _unblocked_karaoke()
        mock_get_instance.return_value = mock_karaoke

        client.get("/pause?user=%20%20")  # "  " (spaces only)

        mock_karaoke.playback_controller.pause.assert_not_called()

    @patch("pikaraoke.routes.controller.get_karaoke_instance")
    @patch("pikaraoke.routes.controller.broadcast_event")
    def test_flagged_ip_is_blocked_even_with_a_user(
        self, mock_broadcast, mock_get_instance, client
    ):
        mock_karaoke = MagicMock()
        mock_karaoke.ip_blocklist.is_blocked.return_value = True
        mock_get_instance.return_value = mock_karaoke

        response = client.get("/vol_up?user=RealPerson")

        assert response.status_code == 302
        mock_karaoke.vol_up.assert_not_called()
        mock_karaoke.audit_log.record.assert_not_called()
        mock_broadcast.assert_not_called()

    @patch("pikaraoke.routes.controller.get_karaoke_instance")
    @patch("pikaraoke.routes.controller.broadcast_event")
    def test_unflagged_ip_with_user_is_not_blocked(self, mock_broadcast, mock_get_instance, client):
        mock_karaoke = _unblocked_karaoke()
        mock_get_instance.return_value = mock_karaoke

        client.get("/vol_up?user=RealPerson")

        mock_karaoke.vol_up.assert_called_once()
