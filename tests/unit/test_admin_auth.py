"""Regression tests for /auth: open-redirect protection and cookie hardening.

1. next_url validation used to accept "//evil.com" (protocol-relative), which
   startswith("/") alone does not reject -- browsers treat it as an off-site
   redirect.
2. The admin cookie (which holds the raw password) was set without
   httponly/samesite, so any future XSS could read it directly via JS.
"""

from unittest.mock import MagicMock, patch

import pytest
import werkzeug
from flask import Flask

if not hasattr(werkzeug, "__version__"):
    werkzeug.__version__ = "3.0.0"

from pikaraoke.routes.admin import admin_bp


@pytest.fixture
def app():
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(admin_bp)
    app.extensions["babel"] = MagicMock()
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@patch("pikaraoke.routes.admin._", side_effect=lambda x: x)
@patch("pikaraoke.routes.admin.get_admin_password", return_value="correct-password")
class TestAuthOpenRedirect:
    def test_protocol_relative_next_url_is_rejected(self, mock_get_password, mock_gettext, client):
        response = client.post(
            "/auth", data={"admin_password": "correct-password", "next": "//evil.com"}
        )

        assert response.status_code == 302
        assert response.headers["Location"] == "/"

    def test_normal_relative_next_url_is_allowed(self, mock_get_password, mock_gettext, client):
        response = client.post(
            "/auth", data={"admin_password": "correct-password", "next": "/queue"}
        )

        assert response.headers["Location"] == "/queue"

    def test_absolute_url_next_is_rejected(self, mock_get_password, mock_gettext, client):
        response = client.post(
            "/auth",
            data={"admin_password": "correct-password", "next": "https://evil.com"},
        )

        assert response.headers["Location"] == "/"


@patch("pikaraoke.routes.admin._", side_effect=lambda x: x)
@patch("pikaraoke.routes.admin.get_admin_password", return_value="correct-password")
class TestAuthCookieHardening:
    def test_admin_cookie_is_httponly(self, mock_get_password, mock_gettext, client):
        response = client.post("/auth", data={"admin_password": "correct-password", "next": "/"})

        set_cookie = response.headers.get("Set-Cookie", "")
        assert "HttpOnly" in set_cookie

    def test_incorrect_password_does_not_set_cookie(self, mock_get_password, mock_gettext, client):
        response = client.post("/auth", data={"admin_password": "wrong-password", "next": "/"})

        assert "admin=" not in response.headers.get("Set-Cookie", "")
