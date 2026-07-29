"""Tests for playback controller routes, focused on the /skip admin gate."""

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
        mock_broadcast.assert_not_called()

    @patch("pikaraoke.routes.controller.is_admin", return_value=True)
    @patch("pikaraoke.routes.controller.get_karaoke_instance")
    @patch("pikaraoke.routes.controller.broadcast_event")
    def test_admin_skip_still_works(
        self, mock_broadcast, mock_get_instance, mock_is_admin, client
    ):
        mock_karaoke = MagicMock()
        mock_get_instance.return_value = mock_karaoke

        response = client.get("/skip")

        assert response.status_code == 302
        mock_karaoke.playback_controller.skip.assert_called_once()
        mock_broadcast.assert_called_once_with("skip", "user command")
