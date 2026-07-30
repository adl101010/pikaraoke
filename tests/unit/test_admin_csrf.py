"""Regression tests for CSRF protection on the destructive admin routes.

/quit, /shutdown, /reboot, and /expand_fs used to be plain GET links. Even
with the admin cookie hardened to SameSite=Lax, a top-level navigation (e.g.
a malicious page doing `location = 'http://victim/quit'`) still carries the
cookie, so a logged-in admin could be tricked into triggering them. They are
now POST-only and require a per-session CSRF token (pikaraoke.lib.current_app
get_csrf_token/verify_csrf_token) submitted alongside the request.
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

    # The routes under test redirect to url_for("home.home"); stub it out
    # since home_bp isn't registered here.
    app.add_url_rule("/", endpoint="home.home", view_func=lambda: "")

    return app


@pytest.fixture
def client(app):
    return app.test_client()


def _set_session_token(client, token="valid-token"):
    with client.session_transaction() as sess:
        sess["csrf_token"] = token
    return token


@patch("pikaraoke.routes.admin._", side_effect=lambda x: x)
@patch("pikaraoke.routes.admin.threading.Thread")
@patch("pikaraoke.routes.admin.get_karaoke_instance")
@patch("pikaraoke.routes.admin.is_admin", return_value=True)
class TestDestructiveRoutesRequireCsrfToken:
    @pytest.mark.parametrize("path", ["/quit", "/shutdown", "/reboot"])
    def test_missing_token_is_rejected(
        self, mock_is_admin, mock_get_instance, mock_thread, mock_gettext, client, path
    ):
        mock_get_instance.return_value = MagicMock(is_raspberry_pi=True)

        response = client.post(path, data={})

        assert response.status_code == 302
        mock_thread.assert_not_called()

    @pytest.mark.parametrize("path", ["/quit", "/shutdown", "/reboot"])
    def test_wrong_token_is_rejected(
        self, mock_is_admin, mock_get_instance, mock_thread, mock_gettext, client, path
    ):
        mock_get_instance.return_value = MagicMock(is_raspberry_pi=True)
        _set_session_token(client, "correct-token")

        response = client.post(path, data={"csrf_token": "wrong-token"})

        assert response.status_code == 302
        mock_thread.assert_not_called()

    @pytest.mark.parametrize("path", ["/quit", "/shutdown", "/reboot"])
    def test_correct_token_is_accepted(
        self, mock_is_admin, mock_get_instance, mock_thread, mock_gettext, client, path
    ):
        mock_get_instance.return_value = MagicMock(is_raspberry_pi=True)
        token = _set_session_token(client)

        response = client.post(path, data={"csrf_token": token})

        assert response.status_code == 302
        mock_thread.assert_called_once()
        mock_thread.return_value.start.assert_called_once()

    def test_expand_fs_requires_token_on_raspberry_pi(
        self, mock_is_admin, mock_get_instance, mock_thread, mock_gettext, client
    ):
        mock_get_instance.return_value = MagicMock(is_raspberry_pi=True)

        response = client.post("/expand_fs", data={})

        assert response.status_code == 302
        mock_thread.assert_not_called()

    def test_expand_fs_with_correct_token_is_accepted(
        self, mock_is_admin, mock_get_instance, mock_thread, mock_gettext, client
    ):
        mock_get_instance.return_value = MagicMock(is_raspberry_pi=True)
        token = _set_session_token(client)

        response = client.post("/expand_fs", data={"csrf_token": token})

        assert response.status_code == 302
        mock_thread.assert_called_once()

    def test_expand_fs_rejects_on_non_pi_regardless_of_token(
        self, mock_is_admin, mock_get_instance, mock_thread, mock_gettext, client
    ):
        mock_get_instance.return_value = MagicMock(is_raspberry_pi=False)
        token = _set_session_token(client)

        response = client.post("/expand_fs", data={"csrf_token": token})

        assert response.status_code == 302
        mock_thread.assert_not_called()


@patch("pikaraoke.routes.admin._", side_effect=lambda x: x)
@patch("pikaraoke.routes.admin.threading.Thread")
@patch("pikaraoke.routes.admin.get_karaoke_instance")
@patch("pikaraoke.routes.admin.is_admin", return_value=False)
class TestDestructiveRoutesStillRequireAdmin:
    """A valid CSRF token must not substitute for the admin check."""

    @pytest.mark.parametrize("path", ["/quit", "/shutdown", "/reboot", "/expand_fs"])
    def test_non_admin_with_valid_token_is_still_blocked(
        self, mock_is_admin, mock_get_instance, mock_thread, mock_gettext, client, path
    ):
        mock_get_instance.return_value = MagicMock(is_raspberry_pi=True)
        token = _set_session_token(client)

        response = client.post(path, data={"csrf_token": token})

        assert response.status_code == 302
        mock_thread.assert_not_called()
