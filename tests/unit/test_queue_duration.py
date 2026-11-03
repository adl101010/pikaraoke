"""Tests for song lengths feeding the queue's running total.

The queue page and the home page show how long the queue will take, which
means every queued song needs a length. Reading one is cheap but not free,
and the same popular songs get queued again and again, so each is measured
once and remembered. None of this may ever stop a song being queued.
"""

import json
import sqlite3
from unittest.mock import MagicMock, patch

import pytest

from pikaraoke.lib.events import EventSystem
from pikaraoke.lib.karaoke_database import KaraokeDatabase
from pikaraoke.lib.preference_manager import PreferenceManager
from pikaraoke.lib.queue_manager import QueueManager
from pikaraoke.lib.song_manager import SongManager

SONG = "/songs/Journey - Dont Stop---dQw4w9WgXcQ.mp4"
OTHER = "/songs/ABBA - Dancing Queen---aB3_x9-Zq1K.mp4"


@pytest.fixture
def db(tmp_path):
    database = KaraokeDatabase(str(tmp_path / "songs.db"))
    yield database
    database.close()


def _add(db, path):
    db.insert_songs([{"file_path": path, "youtube_id": None, "format": "video"}])


# --------------------------------------------------------------------------
# The saved length, on the song's own row
# --------------------------------------------------------------------------


class TestSavedDuration:
    def test_a_new_song_has_no_length_yet(self, db):
        _add(db, SONG)
        assert db.get_song_duration(SONG) is None

    def test_a_saved_length_is_returned(self, db):
        _add(db, SONG)
        db.set_song_duration(SONG, 254)
        assert db.get_song_duration(SONG) == 254

    def test_lengths_belong_to_their_own_song(self, db):
        _add(db, SONG)
        _add(db, OTHER)
        db.set_song_duration(SONG, 254)
        assert db.get_song_duration(OTHER) is None

    def test_overwriting_replaces_the_old_length(self, db):
        _add(db, SONG)
        db.set_song_duration(SONG, 254)
        db.set_song_duration(SONG, 300)
        assert db.get_song_duration(SONG) == 300

    def test_an_unknown_song_has_no_length(self, db):
        assert db.get_song_duration("/songs/never-heard-of-it.mp4") is None

    def test_saving_a_length_does_not_add_the_song(self, db):
        """It's a cache for known songs, not a back door into the library."""
        db.set_song_duration("/songs/stranger.mp4", 200)
        assert db.get_song_duration("/songs/stranger.mp4") is None
        assert "/songs/stranger.mp4" not in db.get_all_song_paths()

    def test_the_length_survives_a_rename(self, db):
        """Renaming updates the path in place, so the saved length goes with it."""
        _add(db, SONG)
        db.set_song_duration(SONG, 254)
        db.update_path(SONG, "/songs/Renamed---dQw4w9WgXcQ.mp4")
        assert db.get_song_duration("/songs/Renamed---dQw4w9WgXcQ.mp4") == 254

    def test_the_length_survives_a_rescan(self, db):
        """A rescan that sees the same file must not wipe what was measured."""
        _add(db, SONG)
        db.set_song_duration(SONG, 254)
        _add(db, SONG)  # INSERT OR IGNORE, as the scanner does
        assert db.get_song_duration(SONG) == 254

    def test_the_length_is_saved_as_whole_seconds(self, db):
        _add(db, SONG)
        db.set_song_duration(SONG, 254.0)
        assert db.get_song_duration(SONG) == 254
        assert isinstance(db.get_song_duration(SONG), int)


class TestDurationColumnMigration:
    def test_an_older_database_gains_the_column(self, tmp_path):
        """Existing libraries must open cleanly and keep their songs."""
        path = str(tmp_path / "old.db")
        conn = sqlite3.connect(path)
        conn.executescript(
            """
            CREATE TABLE songs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT UNIQUE NOT NULL,
                youtube_id TEXT,
                format TEXT NOT NULL,
                artist TEXT, title TEXT, variant TEXT, year INTEGER, genre TEXT,
                metadata_status TEXT DEFAULT 'pending',
                enrichment_attempts INTEGER DEFAULT 0,
                last_enrichment_attempt TEXT,
                play_count INTEGER NOT NULL DEFAULT 0,
                last_played_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO songs (file_path, format, play_count)
            VALUES ('/songs/kept.mp4', 'video', 7);
            """
        )
        conn.commit()
        conn.close()

        database = KaraokeDatabase(path)
        try:
            assert database.get_song_duration("/songs/kept.mp4") is None
            database.set_song_duration("/songs/kept.mp4", 180)
            assert database.get_song_duration("/songs/kept.mp4") == 180
            assert database.get_play_counts()["/songs/kept.mp4"] == 7
        finally:
            database.close()

    def test_opening_twice_does_not_fail(self, tmp_path):
        """The migration runs on every start, so it has to be repeatable."""
        path = str(tmp_path / "twice.db")
        KaraokeDatabase(path).close()
        KaraokeDatabase(path).close()


# --------------------------------------------------------------------------
# SongManager: measure once, remember, never guess
# --------------------------------------------------------------------------


@pytest.fixture
def songs(db, tmp_path):
    return SongManager(download_path=str(tmp_path), db=db)


class TestMeasureOnceAndRemember:
    @patch("pikaraoke.lib.song_manager.get_media_duration", return_value=254)
    def test_an_unmeasured_song_is_measured_and_saved(self, probe, songs, db):
        _add(db, SONG)

        assert songs.get_duration(SONG) == 254

        probe.assert_called_once_with(SONG)
        assert db.get_song_duration(SONG) == 254

    @patch("pikaraoke.lib.song_manager.get_media_duration", return_value=254)
    def test_the_second_ask_does_not_measure_again(self, probe, songs, db):
        _add(db, SONG)

        songs.get_duration(SONG)
        songs.get_duration(SONG)
        songs.get_duration(SONG)

        assert probe.call_count == 1

    @patch("pikaraoke.lib.song_manager.get_media_duration", return_value=999)
    def test_a_saved_length_is_used_without_measuring(self, probe, songs, db):
        _add(db, SONG)
        db.set_song_duration(SONG, 254)

        assert songs.get_duration(SONG) == 254

        probe.assert_not_called()

    @pytest.mark.parametrize("unreadable", [None, 0])
    @patch("pikaraoke.lib.song_manager.get_media_duration")
    def test_an_unreadable_file_is_unknown_not_zero(self, probe, songs, db, unreadable):
        """Zero would quietly shorten the total; unknown has to stay unknown."""
        probe.return_value = unreadable
        _add(db, SONG)

        assert songs.get_duration(SONG) is None
        assert db.get_song_duration(SONG) is None

    @patch("pikaraoke.lib.song_manager.get_media_duration")
    def test_an_unreadable_file_is_tried_again_next_time(self, probe, songs, db):
        """A transient failure must not be remembered as a permanent one."""
        _add(db, SONG)
        probe.return_value = None
        assert songs.get_duration(SONG) is None

        probe.return_value = 254
        assert songs.get_duration(SONG) == 254

    @pytest.mark.parametrize("name", ["/songs/Karaoke.zip", "/songs/Karaoke.ZIP", "/songs/K.Zip"])
    @patch("pikaraoke.lib.song_manager.get_media_duration")
    def test_zipped_karaoke_is_not_probed(self, probe, songs, db, name):
        """The archive is only unpacked at play time, so probing it would fail."""
        _add(db, name)

        assert songs.get_duration(name) is None

        probe.assert_not_called()

    @patch("pikaraoke.lib.song_manager.get_media_duration")
    def test_a_zipped_song_is_known_after_it_plays(self, probe, songs, db):
        _add(db, "/songs/Karaoke.zip")

        songs.remember_duration("/songs/Karaoke.zip", 212)

        assert songs.get_duration("/songs/Karaoke.zip") == 212
        probe.assert_not_called()

    @pytest.mark.parametrize(
        "path,seconds", [("/songs/x.mp4", None), ("/songs/x.mp4", 0), ("", 200), (None, 200)]
    )
    def test_remembering_ignores_nothing_useful(self, songs, db, path, seconds):
        _add(db, "/songs/x.mp4")
        songs.remember_duration(path, seconds)
        assert db.get_song_duration("/songs/x.mp4") is None

    @pytest.mark.parametrize("ext", [".mp4", ".mkv", ".webm", ".mp3", ".avi", ".mov"])
    @patch("pikaraoke.lib.song_manager.get_media_duration", return_value=200)
    def test_everything_but_zips_is_measured_directly(self, probe, songs, db, ext):
        """An .mp3 is the audio half of a CDG pair and probes fine on its own."""
        path = f"/songs/Song---dQw4w9WgXcQ{ext}"
        _add(db, path)
        assert songs.get_duration(path) == 200


# --------------------------------------------------------------------------
# The queue entry
# --------------------------------------------------------------------------


@pytest.fixture
def preferences(tmp_path):
    return PreferenceManager(config_file_path=str(tmp_path / "config.ini"))


def _title(path, *args):
    return path.rsplit("/", 1)[-1].split("---")[0]


def _queue(preferences, get_duration=None, **extra):
    return QueueManager(
        preferences=preferences,
        events=EventSystem(),
        get_now_playing_user=lambda: None,
        filename_from_path=_title,
        get_available_songs=lambda: [],
        get_duration=get_duration,
        **extra,
    )


class TestQueueEntryLength:
    def test_a_queued_song_carries_its_length(self, preferences):
        qm = _queue(preferences, get_duration=lambda path: 254)
        qm.enqueue(SONG, "Dave", device_id="phone-A")
        assert qm.queue[0]["duration"] == 254

    def test_the_length_is_looked_up_for_the_song_queued(self, preferences):
        lengths = {SONG: 254, OTHER: 231}
        qm = _queue(preferences, get_duration=lengths.get)
        qm.enqueue(SONG, "Dave")
        qm.enqueue(OTHER, "Erin")
        assert [item["duration"] for item in qm.queue] == [254, 231]

    def test_without_a_lookup_the_length_is_unknown(self, preferences):
        qm = _queue(preferences)
        qm.enqueue(SONG, "Dave")
        assert qm.queue[0]["duration"] is None

    def test_an_unknown_length_is_kept_as_unknown(self, preferences):
        qm = _queue(preferences, get_duration=lambda path: None)
        qm.enqueue(SONG, "Dave")
        assert qm.queue[0]["duration"] is None

    @pytest.mark.parametrize("error", [OSError("disk gone"), ValueError("bad"), RuntimeError("x")])
    def test_a_failing_lookup_never_stops_a_song_being_queued(self, preferences, error):
        """The total is a convenience; the song is the point."""
        qm = _queue(preferences, get_duration=MagicMock(side_effect=error))

        accepted, _message = qm.enqueue(SONG, "Dave")

        assert accepted is True
        assert len(qm.queue) == 1
        assert qm.queue[0]["duration"] is None

    @pytest.mark.parametrize("front", [False, True])
    def test_the_length_is_attached_whichever_end_it_joins(self, preferences, front):
        qm = _queue(preferences, get_duration=lambda path: 254)
        qm.enqueue(OTHER, "Erin")
        qm.enqueue(SONG, "Dave", add_to_front=front)
        assert all(item["duration"] == 254 for item in qm.queue)

    def test_the_length_is_attached_with_fair_queueing_on(self, preferences):
        preferences.set("enable_fair_queue", True)
        qm = _queue(preferences, get_duration=lambda path: 254)
        qm.enqueue(SONG, "Dave")
        qm.enqueue(OTHER, "Erin")
        assert all(item["duration"] == 254 for item in qm.queue)

    def test_a_refused_song_is_not_measured(self, preferences):
        """Already-queued songs are turned away before any work is done."""
        lookup = MagicMock(return_value=254)
        qm = _queue(preferences, get_duration=lookup)
        qm.enqueue(SONG, "Dave")
        lookup.reset_mock()

        accepted, _message = qm.enqueue(SONG, "Dave")

        assert accepted is False
        lookup.assert_not_called()

    def test_reordering_keeps_each_songs_length(self, preferences):
        lengths = {SONG: 254, OTHER: 231}
        qm = _queue(preferences, get_duration=lengths.get)
        qm.enqueue(SONG, "Dave")
        qm.enqueue(OTHER, "Erin")

        qm.queue.reverse()

        assert {item["file"]: item["duration"] for item in qm.queue} == lengths


class TestWhatTheBrowserIsTold:
    def test_the_length_reaches_the_browser(self, preferences):
        qm = _queue(preferences, get_duration=lambda path: 254)
        qm.enqueue(SONG, "Dave", device_id="phone-A")
        assert qm.public_queue[0]["duration"] == 254

    def test_the_device_token_still_does_not(self, preferences):
        """Adding a field must not widen what a guest can read."""
        qm = _queue(preferences, get_duration=lambda path: 254)
        qm.enqueue(SONG, "Dave", device_id="phone-A")
        assert "device_id" not in qm.public_queue[0]

    def test_an_unknown_length_survives_serialisation(self, preferences):
        """get_queue returns json.dumps of this, so None has to round-trip."""
        qm = _queue(preferences, get_duration=lambda path: None)
        qm.enqueue(SONG, "Dave")
        assert json.loads(json.dumps(qm.public_queue))[0]["duration"] is None

    def test_the_lengths_add_up_to_the_expected_total(self, preferences):
        """The same sum the pages do, on the figures the mock-up used."""
        durations = [274, 168, 261, 250, 223, 231, 415, 201, 258, 257]
        paths = {f"/songs/Song {i}---aaaaaaaaaa{i}.mp4": d for i, d in enumerate(durations)}
        qm = _queue(preferences, get_duration=paths.get)
        for index, path in enumerate(paths):
            qm.enqueue(path, f"Guest{index}")

        total = sum(item["duration"] for item in qm.public_queue)

        assert total == 2538
        assert f"{total // 60}m {total % 60:02d}s" == "42m 18s"


# --------------------------------------------------------------------------
# The wiring in Karaoke
# --------------------------------------------------------------------------


class TestPlaybackRemembersLength:
    """A zipped song can't be measured until it plays, so playing teaches us."""

    def test_the_song_that_started_has_its_length_saved(self):
        from types import SimpleNamespace

        from pikaraoke.karaoke import Karaoke

        song_manager = MagicMock()
        fake = SimpleNamespace(
            song_manager=song_manager,
            playback_controller=SimpleNamespace(
                now_playing_filename="/songs/Karaoke.zip", now_playing_duration=212
            ),
        )

        Karaoke._remember_now_playing_duration(fake)

        song_manager.remember_duration.assert_called_once_with("/songs/Karaoke.zip", 212)

    def test_the_handlers_are_actually_registered(self):
        """The real Karaoke is too heavy to build here, so guard the wiring itself.

        Without these two lines nothing fails anywhere: the totals just quietly
        stop including any song that hasn't been measured.
        """
        from pathlib import Path

        source = (Path(__file__).resolve().parents[2] / "pikaraoke" / "karaoke.py").read_text(
            encoding="utf-8"
        )
        assert 'self.events.on("playback_started", self._remember_now_playing_duration)' in source
        assert "get_duration=self.song_manager.get_duration" in source


class TestKeyChangeKeepsTheOwner:
    def test_a_transposed_song_is_still_the_singers(self):
        """Changing key re-queues the song; it must stay theirs, or "Skip mine" and
        the your-turn card stop recognising it mid-song."""
        from types import SimpleNamespace

        from pikaraoke.karaoke import Karaoke

        queue_manager, playback = MagicMock(), MagicMock()
        playback.now_playing_filename = "/songs/a.mp4"
        playback.now_playing_user = "Liv"
        playback.now_playing_device = "phone-a"
        playback.now_playing = "A"
        fake = SimpleNamespace(
            queue_manager=queue_manager,
            playback_controller=playback,
            log_and_send=lambda *args: None,
        )

        Karaoke.transpose_current(fake, 2)

        queue_manager.enqueue.assert_called_once_with(
            "/songs/a.mp4", "Liv", 2, True, device_id="phone-a"
        )
