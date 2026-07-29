"""Tests for Flask application-context helpers, focused on get_client_ip()."""

import werkzeug
from flask import Flask

if not hasattr(werkzeug, "__version__"):
    werkzeug.__version__ = "3.0.0"

from pikaraoke.lib.current_app import get_client_ip


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
