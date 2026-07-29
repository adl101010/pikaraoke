"""Tests for Flask application-context helpers: get_client_ip() and is_action_blocked()."""

from unittest.mock import MagicMock

import werkzeug
from flask import Flask

if not hasattr(werkzeug, "__version__"):
    werkzeug.__version__ = "3.0.0"

from pikaraoke.lib.current_app import get_client_ip, is_action_blocked


def _app():
    app = Flask(__name__)

    @app.route("/probe")
    def probe():
        return get_client_ip()

    return app


def test_uses_remote_addr_when_no_forwarded_header():
    client = _app().test_client()
    response = client.get("/probe")
    assert response.data.decode() == "127.0.0.1"


def test_prefers_x_forwarded_for_first_hop():
    client = _app().test_client()
    response = client.get("/probe", headers={"X-Forwarded-For": "203.0.113.5, 10.0.0.1"})
    assert response.data.decode() == "203.0.113.5"


def test_strips_whitespace_from_forwarded_header():
    client = _app().test_client()
    response = client.get("/probe", headers={"X-Forwarded-For": "  203.0.113.9  ,10.0.0.1"})
    assert response.data.decode() == "203.0.113.9"


def _blocked_app(is_ip_blocked, user):
    app = Flask(__name__)
    k = MagicMock()
    k.ip_blocklist.is_blocked.return_value = is_ip_blocked

    @app.route("/probe")
    def probe():
        return str(is_action_blocked(k, user))

    return app


def test_action_allowed_with_real_user_and_unflagged_ip():
    client = _blocked_app(is_ip_blocked=False, user="Alice").test_client()
    assert client.get("/probe").data.decode() == "False"


def test_action_blocked_when_ip_flagged_even_with_a_user():
    client = _blocked_app(is_ip_blocked=True, user="Alice").test_client()
    assert client.get("/probe").data.decode() == "True"


def test_action_blocked_when_user_is_empty():
    client = _blocked_app(is_ip_blocked=False, user="").test_client()
    assert client.get("/probe").data.decode() == "True"


def test_action_blocked_when_user_is_whitespace_only():
    client = _blocked_app(is_ip_blocked=False, user="   ").test_client()
    assert client.get("/probe").data.decode() == "True"


def test_action_blocked_when_user_is_none():
    client = _blocked_app(is_ip_blocked=False, user=None).test_client()
    assert client.get("/probe").data.decode() == "True"
