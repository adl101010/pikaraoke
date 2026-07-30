"""Tests for the /bg_music/<file> route, in particular path-traversal protection.

<file> is an unauthenticated route parameter joined directly with bg_music_path
and streamed via send_file() -- must not allow escaping bg_music_path.
"""

from unittest.mock import MagicMock, patch

import pytest
import werkzeug
from flask import Flask

if not hasattr(werkzeug, "__version__"):
    werkzeug.__version__ = "3.0.0"

from pikaraoke.routes.background_music import background_music_bp


@pytest.fixture
def app():
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(background_music_bp)
    app.extensions["babel"] = MagicMock()
    return app


@pytest.fixture
def client(app):
    return app.test_client()


class TestBgMusicTraversal:
    @patch("pikaraoke.routes.background_music.get_karaoke_instance")
    def test_serves_file_within_bg_music_path(self, mock_get_instance, client, tmp_path):
        bg_dir = tmp_path / "bg_music"
        bg_dir.mkdir()
        (bg_dir / "song.mp3").write_bytes(b"fake mp3 data")
        mock_karaoke = MagicMock()
        mock_karaoke.bg_music_path = str(bg_dir)
        mock_get_instance.return_value = mock_karaoke

        response = client.get("/bg_music/song.mp3")

        assert response.status_code == 200

    @patch("pikaraoke.routes.background_music.get_karaoke_instance")
    def test_rejects_traversal_outside_bg_music_path(self, mock_get_instance, client, tmp_path):
        bg_dir = tmp_path / "bg_music"
        bg_dir.mkdir()
        secret = tmp_path / "secret.txt"
        secret.write_text("should not be readable via bg_music")
        mock_karaoke = MagicMock()
        mock_karaoke.bg_music_path = str(bg_dir)
        mock_get_instance.return_value = mock_karaoke

        response = client.get("/bg_music/..%2Fsecret.txt")

        assert response.status_code == 404

    @patch("pikaraoke.routes.background_music.get_karaoke_instance")
    def test_rejects_nonexistent_file_in_path(self, mock_get_instance, client, tmp_path):
        bg_dir = tmp_path / "bg_music"
        bg_dir.mkdir()
        mock_karaoke = MagicMock()
        mock_karaoke.bg_music_path = str(bg_dir)
        mock_get_instance.return_value = mock_karaoke

        response = client.get("/bg_music/does-not-exist.mp3")

        assert response.status_code == 404
