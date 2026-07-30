"""Tests for Flask application-context helpers: get_client_ip(), is_action_blocked(),
and the CSRF token helpers used to guard destructive admin routes.
"""

from unittest.mock import MagicMock

import werkzeug
from flask import Flask

if not hasattr(werkzeug, "__version__"):
    werkzeug.__version__ = "3.0.0"

from pikaraoke.lib.current_app import (
    get_client_ip,
    get_csrf_token,
    is_action_blocked,
    verify_csrf_token,
)


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


def test_prefers_cf_connecting_ip_over_x_forwarded_for():
    client = _app().test_client()
    response = client.get(
        "/probe",
        headers={"CF-Connecting-IP": "198.51.100.7", "X-Forwarded-For": "203.0.113.5, 10.0.0.1"},
    )
    assert response.data.decode() == "198.51.100.7"


def test_uses_cf_connecting_ip_when_no_forwarded_header():
    client = _app().test_client()
    response = client.get("/probe", headers={"CF-Connecting-IP": "198.51.100.7"})
    assert response.data.decode() == "198.51.100.7"


def test_strips_whitespace_from_cf_connecting_ip():
    client = _app().test_client()
    response = client.get("/probe", headers={"CF-Connecting-IP": "  198.51.100.7  "})
    assert response.data.decode() == "198.51.100.7"


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


def _csrf_app():
    app = Flask(__name__)
    app.secret_key = "test"

    @app.route("/get-token")
    def get_token():
        return get_csrf_token()

    @app.route("/verify", methods=["POST"])
    def verify():
        return str(verify_csrf_token())

    return app


def test_get_csrf_token_is_stable_within_a_session():
    client = _csrf_app().test_client()
    first = client.get("/get-token").data.decode()
    second = client.get("/get-token").data.decode()
    assert first == second


def test_get_csrf_token_differs_across_sessions():
    app = _csrf_app()
    token_a = app.test_client().get("/get-token").data.decode()
    token_b = app.test_client().get("/get-token").data.decode()
    assert token_a != token_b


def test_verify_csrf_token_accepts_matching_token():
    client = _csrf_app().test_client()
    token = client.get("/get-token").data.decode()
    response = client.post("/verify", data={"csrf_token": token})
    assert response.data.decode() == "True"


def test_verify_csrf_token_rejects_wrong_token():
    client = _csrf_app().test_client()
    client.get("/get-token")
    response = client.post("/verify", data={"csrf_token": "not-the-token"})
    assert response.data.decode() == "False"


def test_verify_csrf_token_rejects_missing_token():
    client = _csrf_app().test_client()
    client.get("/get-token")
    response = client.post("/verify", data={})
    assert response.data.decode() == "False"


def test_verify_csrf_token_rejects_when_no_token_was_ever_issued():
    client = _csrf_app().test_client()
    response = client.post("/verify", data={"csrf_token": ""})
    assert response.data.decode() == "False"
