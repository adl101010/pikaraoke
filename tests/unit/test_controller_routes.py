"""Tests for playback controller routes: admin gating and audit logging."""

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


class TestSkipRoute:
    """Skipping the current song requires admin."""

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


class TestAuditLogging:
    """Pause/transpose/volume aren't admin-gated, but should still be logged."""

    @patch("pikaraoke.routes.controller.get_karaoke_instance")
    @patch("pikaraoke.routes.controller.broadcast_event")
    @patch("pikaraoke.routes.controller._", side_effect=lambda x: x)
    def test_pause_logs_paused_when_currently_playing(
        self, mock_gettext, mock_broadcast, mock_get_instance, client
    ):
        mock_karaoke = MagicMock()
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
        mock_karaoke = MagicMock()
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
    def test_pause_without_user_param_logs_empty_string(
        self, mock_gettext, mock_broadcast, mock_get_instance, client
    ):
        mock_karaoke = MagicMock()
        mock_karaoke.playback_controller.is_paused = False
        mock_karaoke.playback_controller.now_playing = "Song A"
        mock_get_instance.return_value = mock_karaoke

        client.get("/pause")

        mock_karaoke.audit_log.record.assert_called_once_with(
            "", "Paused playback", "Song A", "127.0.0.1"
        )

    @patch("pikaraoke.routes.controller.get_karaoke_instance")
    @patch("pikaraoke.routes.controller.broadcast_event")
    @patch("pikaraoke.routes.controller._", side_effect=lambda x: x)
    def test_transpose_logs_semitones_and_song(
        self, mock_gettext, mock_broadcast, mock_get_instance, client
    ):
        mock_karaoke = MagicMock()
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
        mock_karaoke = MagicMock()
        mock_get_instance.return_value = mock_karaoke

        client.get("/volume/0.5?user=Dana")

        mock_karaoke.audit_log.record.assert_called_once_with(
            "Dana", "Changed volume", "0.5", "127.0.0.1"
        )

    @patch("pikaraoke.routes.controller.get_karaoke_instance")
    @patch("pikaraoke.routes.controller.broadcast_event")
    @patch("pikaraoke.routes.controller._", side_effect=lambda x: x)
    def test_vol_up_logs(self, mock_gettext, mock_broadcast, mock_get_instance, client):
        mock_karaoke = MagicMock()
        mock_get_instance.return_value = mock_karaoke

        client.get("/vol_up?user=Eve")

        mock_karaoke.audit_log.record.assert_called_once_with(
            "Eve", "Increased volume", "", "127.0.0.1"
        )

    @patch("pikaraoke.routes.controller.get_karaoke_instance")
    @patch("pikaraoke.routes.controller.broadcast_event")
    @patch("pikaraoke.routes.controller._", side_effect=lambda x: x)
    def test_vol_down_logs(self, mock_gettext, mock_broadcast, mock_get_instance, client):
        mock_karaoke = MagicMock()
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
