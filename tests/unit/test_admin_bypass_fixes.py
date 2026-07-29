"""Regression tests for two admin-auth bypasses fixed in files.py and batch_song_renamer.py.

1. files.rename_file() used to flash an "unauthorized" message but fall through
   and rename the file anyway when the caller was not an admin.
2. batch_song_renamer.rename_song() had no is_admin() check at all.
"""

import json
from unittest.mock import MagicMock, patch

import pytest
import werkzeug
from flask import Flask

if not hasattr(werkzeug, "__version__"):
    werkzeug.__version__ = "3.0.0"

from pikaraoke.routes.batch_song_renamer import batch_song_renamer_bp
from pikaraoke.routes.files import files_bp


@pytest.fixture
def files_app():
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(files_bp)
    app.extensions["babel"] = MagicMock()
    return app


@pytest.fixture
def files_client(files_app):
    return files_app.test_client()


@pytest.fixture
def renamer_app():
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(batch_song_renamer_bp)
    app.extensions["babel"] = MagicMock()
    return app


@pytest.fixture
def renamer_client(renamer_app):
    return renamer_app.test_client()


class TestFilesEditBypassFixed:
    """/files/edit POST must not rename when the caller isn't an admin."""

    @patch("pikaraoke.routes.files.is_admin", return_value=False)
    @patch("pikaraoke.routes.files.get_karaoke_instance")
    @patch("pikaraoke.routes.files._", side_effect=lambda x: x)
    @patch("os.path.isfile", return_value=False)
    def test_non_admin_rename_is_blocked(
        self, mock_isfile, mock_gettext, mock_get_instance, mock_is_admin, files_client
    ):
        mock_karaoke = MagicMock()
        # Not in queue, so the only thing that should block the rename is the admin check.
        mock_karaoke.queue_manager.is_song_in_queue.return_value = False
        mock_get_instance.return_value = mock_karaoke

        response = files_client.post(
            "/files/edit",
            data={
                "old_file_name": "/songs/Old Name---abc12345678.mp4",
                "new_file_name": "New Name",
            },
        )

        assert response.status_code == 302
        mock_karaoke.song_manager.rename.assert_not_called()

    @patch("pikaraoke.routes.files.is_admin", return_value=True)
    @patch("pikaraoke.routes.files.get_karaoke_instance")
    @patch("pikaraoke.routes.files._", side_effect=lambda x: x)
    @patch("os.path.isfile", return_value=False)
    def test_admin_rename_still_works(
        self, mock_isfile, mock_gettext, mock_get_instance, mock_is_admin, files_client
    ):
        mock_karaoke = MagicMock()
        mock_karaoke.queue_manager.is_song_in_queue.return_value = False
        mock_get_instance.return_value = mock_karaoke

        response = files_client.post(
            "/files/edit",
            data={
                "old_file_name": "/songs/Old Name---abc12345678.mp4",
                "new_file_name": "New Name",
            },
        )

        assert response.status_code == 302
        mock_karaoke.song_manager.rename.assert_called_once()


class TestBatchRenamerBypassFixed:
    """/batch-song-renamer/rename-song POST must not rename when not an admin."""

    @patch("pikaraoke.routes.batch_song_renamer.is_admin", return_value=False)
    @patch("pikaraoke.routes.batch_song_renamer.get_karaoke_instance")
    @patch("pikaraoke.routes.batch_song_renamer._", side_effect=lambda x: x)
    @patch("os.path.isfile", return_value=False)
    def test_non_admin_rename_is_blocked(
        self, mock_isfile, mock_gettext, mock_get_instance, mock_is_admin, renamer_client
    ):
        mock_karaoke = MagicMock()
        # Not in queue, so the only thing that should block the rename is the admin check.
        mock_karaoke.queue_manager.is_song_in_queue.return_value = False
        mock_karaoke.song_manager.filename_from_path.return_value = "Old Name"
        mock_karaoke.song_manager.download_path = "/songs"
        mock_get_instance.return_value = mock_karaoke

        response = renamer_client.post(
            "/batch-song-renamer/rename-song",
            data={"old_name": "/songs/Old Name---abc12345678.mp4", "new_name": "New Name"},
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["success"] is False
        mock_karaoke.song_manager.rename.assert_not_called()

    @patch("pikaraoke.routes.batch_song_renamer.is_admin", return_value=True)
    @patch("pikaraoke.routes.batch_song_renamer.get_karaoke_instance")
    @patch("os.path.isfile", return_value=False)
    def test_admin_rename_still_works(
        self, mock_isfile, mock_get_instance, mock_is_admin, renamer_client
    ):
        mock_karaoke = MagicMock()
        mock_karaoke.queue_manager.is_song_in_queue.return_value = False
        mock_karaoke.song_manager.filename_from_path.return_value = "Old Name"
        mock_karaoke.song_manager.download_path = "/songs"
        mock_get_instance.return_value = mock_karaoke

        response = renamer_client.post(
            "/batch-song-renamer/rename-song",
            data={"old_name": "/songs/Old Name---abc12345678.mp4", "new_name": "New Name"},
        )

        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["success"] is True
        mock_karaoke.song_manager.rename.assert_called_once()
