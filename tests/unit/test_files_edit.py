"""The Edit Song page marks the names it saves as typed by hand."""

from unittest.mock import MagicMock, patch

import pytest
import werkzeug
from flask import Flask

if not hasattr(werkzeug, "__version__"):
    werkzeug.__version__ = "3.0.0"

from pikaraoke.routes.files import files_bp


@pytest.fixture
def client():
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(files_bp)
    app.extensions["babel"] = MagicMock()
    return app.test_client()


@pytest.fixture
def karaoke():
    k = MagicMock()
    k.queue_manager.is_song_in_queue.return_value = False
    with (
        patch("pikaraoke.routes.files.is_admin", return_value=True),
        patch("pikaraoke.routes.files.get_karaoke_instance", return_value=k),
        patch("pikaraoke.routes.files._", side_effect=lambda x: x),
        patch("os.path.isfile", return_value=False),
    ):
        yield k


def _save(client, new_name):
    return client.post(
        "/files/edit",
        data={
            "old_file_name": "/songs/Yuuri - Betelgeuse (No Guide Melody)---abc12345678.mp4",
            "new_file_name": new_name,
        },
    )


def test_a_new_name_is_saved_as_typed(client, karaoke):
    _save(client, "Yuuri - Betelgeuse (Off Vocal)")
    karaoke.song_manager.rename.assert_called_once_with(
        "/songs/Yuuri - Betelgeuse (No Guide Melody)---abc12345678.mp4",
        "Yuuri - Betelgeuse (Off Vocal)---abc12345678",
        typed_by_hand=True,
    )


def test_saving_the_name_unchanged_marks_it_without_renaming(client, karaoke):
    # Songs renamed before typed names were kept get fixed by saving them again.
    response = _save(client, "Yuuri - Betelgeuse (No Guide Melody)")
    assert response.status_code == 302
    karaoke.song_manager.rename.assert_not_called()
    karaoke.song_manager.keep_name_as_typed.assert_called_once_with(
        "/songs/Yuuri - Betelgeuse (No Guide Melody)---abc12345678.mp4"
    )
