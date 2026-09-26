"""Tests for skipping a download of a video the library already has.

A guest searching YouTube has no idea what's already downloaded, so popular
songs get requested over and over. Serving the existing copy saves them a
wait for a file we already hold, and keeps near-duplicates out of the library.
"""

import os
from unittest.mock import MagicMock, patch

import pytest
import werkzeug
from flask import Flask

if not hasattr(werkzeug, "__version__"):
    werkzeug.__version__ = "3.0.0"

from pikaraoke.lib.karaoke_database import KaraokeDatabase
from pikaraoke.routes.search import search_bp

REAL_ID = "dQw4w9WgXcQ"
OTHER_ID = "aB3_x9-Zq1K"


# --------------------------------------------------------------------------
# The database lookup
# --------------------------------------------------------------------------


@pytest.fixture
def db(tmp_path):
    database = KaraokeDatabase(str(tmp_path / "songs.db"))
    yield database
    database.close()


def _add(db, file_path, youtube_id):
    db.insert_songs([{"file_path": file_path, "youtube_id": youtube_id, "format": "video"}])


class TestYoutubeIdLookup:
    def test_finds_a_song_by_its_id(self, db):
        _add(db, "/songs/Bohemian---dQw4w9WgXcQ.mp4", REAL_ID)
        assert db.get_song_by_youtube_id(REAL_ID) == "/songs/Bohemian---dQw4w9WgXcQ.mp4"

    def test_returns_none_for_an_unknown_id(self, db):
        _add(db, "/songs/Bohemian---dQw4w9WgXcQ.mp4", REAL_ID)
        assert db.get_song_by_youtube_id(OTHER_ID) is None

    def test_returns_none_on_an_empty_library(self, db):
        assert db.get_song_by_youtube_id(REAL_ID) is None

    @pytest.mark.parametrize("empty", ["", None])
    def test_returns_none_without_an_id(self, db, empty):
        _add(db, "/songs/Bohemian---dQw4w9WgXcQ.mp4", REAL_ID)
        assert db.get_song_by_youtube_id(empty) is None

    def test_ignores_songs_with_no_id(self, db):
        """Manually added songs have no ID and must not be matched by one."""
        _add(db, "/songs/Ripped From CD.mp4", None)
        assert db.get_song_by_youtube_id(REAL_ID) is None

    @pytest.mark.parametrize(
        "wrong_case",
        ["dqw4w9wgxcq", "DQW4W9WGXCQ", "DqW4W9wGxCq", "dQw4w9WgXcq"],
    )
    def test_id_matching_is_case_sensitive(self, db, wrong_case):
        """YouTube IDs are case-sensitive, so these are genuinely other videos.

        Matching loosely here would hand a guest the wrong song entirely.
        """
        _add(db, "/songs/Bohemian---dQw4w9WgXcQ.mp4", REAL_ID)
        assert db.get_song_by_youtube_id(wrong_case) is None

    def test_partial_ids_do_not_match(self, db):
        _add(db, "/songs/Bohemian---dQw4w9WgXcQ.mp4", REAL_ID)
        for fragment in ("dQw4w9", "w9WgXcQ", "dQw4w9WgXc"):
            assert db.get_song_by_youtube_id(fragment) is None

    def test_finds_the_id_among_many_songs(self, db):
        for index in range(25):
            _add(
                db, f"/songs/Filler {index}---{'a' * 10}{index % 10}.mp4", f"{'a' * 10}{index % 10}"
            )
        _add(db, "/songs/Target---dQw4w9WgXcQ.mp4", REAL_ID)
        assert db.get_song_by_youtube_id(REAL_ID) == "/songs/Target---dQw4w9WgXcQ.mp4"

    def test_works_for_yt_dlp_style_names(self, db):
        """The scan populates IDs from both naming formats, so both dedupe."""
        _add(db, "/songs/Bohemian [dQw4w9WgXcQ].mp4", REAL_ID)
        assert db.get_song_by_youtube_id(REAL_ID) == "/songs/Bohemian [dQw4w9WgXcQ].mp4"

    def test_survives_a_rename(self, db):
        """Renaming updates the path in place, so the ID still resolves."""
        _add(db, "/songs/Old Name---dQw4w9WgXcQ.mp4", REAL_ID)
        db.update_path("/songs/Old Name---dQw4w9WgXcQ.mp4", "/songs/New Name---dQw4w9WgXcQ.mp4")
        assert db.get_song_by_youtube_id(REAL_ID) == "/songs/New Name---dQw4w9WgXcQ.mp4"


# --------------------------------------------------------------------------
# The download route
# --------------------------------------------------------------------------


@pytest.fixture
def app():
    test_app = Flask(__name__)
    test_app.secret_key = "test"
    test_app.register_blueprint(search_bp)
    test_app.extensions["babel"] = MagicMock()
    return test_app


@pytest.fixture
def client(app):
    return app.test_client()


def _karaoke(existing_path=None):
    k = MagicMock()
    k.db.get_song_by_youtube_id.return_value = existing_path
    k.song_manager.display_name_from_path.return_value = "Bohemian Rhapsody"
    k.queue_manager.enqueue.return_value = [True, "Song added to the queue: Bohemian Rhapsody"]
    return k


def _post(client, queue=False, url=f"https://www.youtube.com/watch?v={REAL_ID}"):
    return client.post(
        "/download",
        json={
            "song_url": url,
            "song_added_by": "Dave",
            "song_title": "Bohemian Rhapsody",
            "queue": queue,
        },
    )


class TestDownloadSkipsWhatWeAlreadyHave:
    @patch("pikaraoke.routes.search.get_karaoke_instance")
    @patch("pikaraoke.routes.search._", side_effect=lambda x: x)
    def test_downloads_when_the_library_lacks_it(self, _gettext, get_instance, client):
        k = _karaoke(existing_path=None)
        get_instance.return_value = k

        response = _post(client)

        assert response.status_code == 200
        assert response.get_json()["status"] == "ok"
        k.download_manager.queue_download.assert_called_once()

    @patch("pikaraoke.routes.search.os.path.isfile", return_value=True)
    @patch("pikaraoke.routes.search.get_karaoke_instance")
    @patch("pikaraoke.routes.search._", side_effect=lambda x: x)
    def test_does_not_download_a_song_we_have(self, _gettext, get_instance, _isfile, client):
        k = _karaoke(existing_path="/songs/Bohemian---dQw4w9WgXcQ.mp4")
        get_instance.return_value = k

        response = _post(client)

        assert response.get_json()["status"] == "already_downloaded"
        k.download_manager.queue_download.assert_not_called()

    @patch("pikaraoke.routes.search.os.path.isfile", return_value=True)
    @patch("pikaraoke.routes.search.get_karaoke_instance")
    @patch("pikaraoke.routes.search._", side_effect=lambda x: x)
    def test_queues_the_existing_copy_when_asked(self, _gettext, get_instance, _isfile, client):
        k = _karaoke(existing_path="/songs/Bohemian---dQw4w9WgXcQ.mp4")
        get_instance.return_value = k

        response = _post(client, queue=True)

        body = response.get_json()
        assert body == {"status": "already_downloaded", "queued": True}
        k.queue_manager.enqueue.assert_called_once()
        assert k.queue_manager.enqueue.call_args[0][0] == "/songs/Bohemian---dQw4w9WgXcQ.mp4"

    @patch("pikaraoke.routes.search.os.path.isfile", return_value=True)
    @patch("pikaraoke.routes.search.get_karaoke_instance")
    @patch("pikaraoke.routes.search._", side_effect=lambda x: x)
    def test_does_not_queue_when_not_asked(self, _gettext, get_instance, _isfile, client):
        k = _karaoke(existing_path="/songs/Bohemian---dQw4w9WgXcQ.mp4")
        get_instance.return_value = k

        response = _post(client, queue=False)

        assert response.get_json() == {"status": "already_downloaded", "queued": False}
        k.queue_manager.enqueue.assert_not_called()

    @patch("pikaraoke.routes.search.os.path.isfile", return_value=True)
    @patch("pikaraoke.routes.search.get_karaoke_instance")
    @patch("pikaraoke.routes.search._", side_effect=lambda x: x)
    def test_tells_the_guest_when_it_is_already_there(
        self, _gettext, get_instance, _isfile, client
    ):
        """Silence would look like the button did nothing."""
        k = _karaoke(existing_path="/songs/Bohemian---dQw4w9WgXcQ.mp4")
        get_instance.return_value = k

        _post(client, queue=False)

        k.events.emit.assert_called_once()
        assert k.events.emit.call_args[0][0] == "notification"

    @patch("pikaraoke.routes.search.os.path.isfile", return_value=True)
    @patch("pikaraoke.routes.search.get_karaoke_instance")
    @patch("pikaraoke.routes.search._", side_effect=lambda x: x)
    def test_reports_a_refused_queue(self, _gettext, get_instance, _isfile, client):
        """Hitting the per-person limit has to be said out loud, not swallowed."""
        k = _karaoke(existing_path="/songs/Bohemian---dQw4w9WgXcQ.mp4")
        k.queue_manager.enqueue.return_value = [False, "You reached the limit"]
        get_instance.return_value = k

        response = _post(client, queue=True)

        assert response.get_json() == {"status": "already_downloaded", "queued": False}
        k.events.emit.assert_called_once()
        assert k.events.emit.call_args[0][1] == "You reached the limit"

    @patch("pikaraoke.routes.search.os.path.isfile", return_value=False)
    @patch("pikaraoke.routes.search.get_karaoke_instance")
    @patch("pikaraoke.routes.search._", side_effect=lambda x: x)
    def test_downloads_again_when_the_file_vanished(self, _gettext, get_instance, _isfile, client):
        """A row can outlive its file if it was deleted outside the app.

        Queueing a song that can't play is worse than downloading it twice.
        """
        k = _karaoke(existing_path="/songs/Deleted---dQw4w9WgXcQ.mp4")
        get_instance.return_value = k

        response = _post(client)

        assert response.get_json()["status"] == "ok"
        k.download_manager.queue_download.assert_called_once()

    @patch("pikaraoke.routes.search.get_karaoke_instance")
    @patch("pikaraoke.routes.search._", side_effect=lambda x: x)
    def test_downloads_when_the_url_has_no_id(self, _gettext, get_instance, client):
        """An unparseable URL can't be deduped, so let the downloader try."""
        k = _karaoke(existing_path=None)
        get_instance.return_value = k

        response = _post(client, url="https://example.com/not-a-video")

        assert response.get_json()["status"] == "ok"
        k.db.get_song_by_youtube_id.assert_not_called()
        k.download_manager.queue_download.assert_called_once()

    @pytest.mark.parametrize(
        "url",
        [
            f"https://www.youtube.com/watch?v={REAL_ID}",
            f"https://youtube.com/watch?v={REAL_ID}",
            f"https://m.youtube.com/watch?v={REAL_ID}",
            f"https://youtu.be/{REAL_ID}",
            f"https://www.youtube.com/watch?v={REAL_ID}&t=42s",
            f"https://www.youtube.com/watch?v={REAL_ID}&list=PLabc&index=2",
            f"https://youtu.be/{REAL_ID}?si=trackingparam",
        ],
    )
    @patch("pikaraoke.routes.search.os.path.isfile", return_value=True)
    @patch("pikaraoke.routes.search.get_karaoke_instance")
    @patch("pikaraoke.routes.search._", side_effect=lambda x: x)
    def test_dedupes_across_url_shapes(self, _gettext, get_instance, _isfile, client, url):
        """The same video arrives in many URL forms; all must dedupe."""
        k = _karaoke(existing_path="/songs/Bohemian---dQw4w9WgXcQ.mp4")
        get_instance.return_value = k

        response = _post(client, url=url)

        assert response.get_json()["status"] == "already_downloaded"
        k.db.get_song_by_youtube_id.assert_called_once_with(REAL_ID)
        k.download_manager.queue_download.assert_not_called()

    @patch("pikaraoke.routes.search.os.path.isfile", return_value=True)
    @patch("pikaraoke.routes.search.get_karaoke_instance")
    @patch("pikaraoke.routes.search._", side_effect=lambda x: x)
    def test_attributes_the_queued_song_to_the_device(
        self, _gettext, get_instance, _isfile, client
    ):
        """Passing the device keeps the per-person limit and self-skip working.

        This is the same action as queueing from the Library page, so it has to
        carry the same identity.
        """
        k = _karaoke(existing_path="/songs/Bohemian---dQw4w9WgXcQ.mp4")
        get_instance.return_value = k

        _post(client, queue=True)

        assert "device_id" in k.queue_manager.enqueue.call_args[1]
