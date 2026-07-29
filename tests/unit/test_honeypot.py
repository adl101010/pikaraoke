"""Tests for the Library page honeypot trap route."""

from unittest.mock import MagicMock, patch

import pytest
import werkzeug
from flask import Flask

if not hasattr(werkzeug, "__version__"):
    werkzeug.__version__ = "3.0.0"

from pikaraoke.routes.files import files_bp


@pytest.fixture
def app():
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(files_bp)
    app.extensions["babel"] = MagicMock()
    return app


@pytest.fixture
def client(app):
    return app.test_client()


class TestHoneypot:
    @patch("pikaraoke.routes.files.get_karaoke_instance")
    def test_visiting_trap_blocks_the_ip(self, mock_get_instance, client):
        mock_karaoke = MagicMock()
        mock_get_instance.return_value = mock_karaoke

        response = client.get("/browse/trap")

        assert response.status_code == 302
        mock_karaoke.ip_blocklist.block.assert_called_once_with(
            "127.0.0.1", "Followed the Library page honeypot link"
        )

    @patch("pikaraoke.routes.files.get_karaoke_instance")
    def test_redirects_to_browse_like_a_normal_page(self, mock_get_instance, client):
        """No error, no special response -- nothing tips off whatever hit it."""
        mock_karaoke = MagicMock()
        mock_get_instance.return_value = mock_karaoke

        response = client.get("/browse/trap")

        assert response.status_code == 302
        assert response.headers["Location"] == "/browse"
