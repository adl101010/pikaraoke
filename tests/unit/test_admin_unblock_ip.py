"""Tests for the admin-only unblock_ip route."""

from unittest.mock import MagicMock, patch

import pytest
import werkzeug
from flask import Flask

if not hasattr(werkzeug, "__version__"):
    werkzeug.__version__ = "3.0.0"

from pikaraoke.routes.admin import admin_bp
from pikaraoke.routes.info import info_bp


@pytest.fixture
def app():
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(admin_bp)
    app.register_blueprint(info_bp)
    app.extensions["babel"] = MagicMock()
    return app


@pytest.fixture
def client(app):
    return app.test_client()


class TestUnblockIp:
    @patch("pikaraoke.routes.admin.is_admin", return_value=False)
    @patch("pikaraoke.routes.admin.get_karaoke_instance")
    @patch("pikaraoke.routes.admin._", side_effect=lambda x: x)
    def test_non_admin_cannot_unblock(self, mock_gettext, mock_get_instance, mock_is_admin, client):
        mock_karaoke = MagicMock()
        mock_get_instance.return_value = mock_karaoke

        response = client.get("/unblock_ip/10.0.0.5")

        assert response.status_code == 302
        mock_karaoke.ip_blocklist.unblock.assert_not_called()

    @patch("pikaraoke.routes.admin.is_admin", return_value=True)
    @patch("pikaraoke.routes.admin.get_karaoke_instance")
    @patch("pikaraoke.routes.admin._", side_effect=lambda x: x)
    def test_admin_can_unblock(self, mock_gettext, mock_get_instance, mock_is_admin, client):
        mock_karaoke = MagicMock()
        mock_get_instance.return_value = mock_karaoke

        response = client.get("/unblock_ip/10.0.0.5")

        assert response.status_code == 302
        mock_karaoke.ip_blocklist.unblock.assert_called_once_with("10.0.0.5")
