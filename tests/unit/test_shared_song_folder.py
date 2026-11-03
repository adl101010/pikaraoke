"""Tests for running several servers off one song folder.

Each server keeps its own database, but they share the folder the songs are
in. So a server has to notice songs the others add, must never mistake a
download in progress for a finished song, and two servers asked for the same
video at once should download it once between them.
"""

import os
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from pikaraoke.karaoke import Karaoke
from pikaraoke.lib.download_manager import DOWNLOAD_LOCK_STALE_SECONDS, DownloadManager
from pikaraoke.lib.events import EventSystem
from pikaraoke.lib.library_scanner import LibraryScanner, ScanResult
from pikaraoke.lib.preference_manager import PreferenceManager
from pikaraoke.lib.song_list import SongList

VIDEO_ID = "dQw4w9WgXcQ"
URL = f"https://www.youtube.com/watch?v={VIDEO_ID}"


# --------------------------------------------------------------------------
# Telling a finished song from the pieces of one in progress
# --------------------------------------------------------------------------


class TestDownloadPiecesAreNotSongs:
    """yt-dlp fetches video and audio separately, then merges them."""

    @pytest.mark.parametrize(
        "piece",
        [f"Song---{VIDEO_ID}.f137.mp4", f"Song---{VIDEO_ID}.f140.mp4", f"Song---{VIDEO_ID}.temp.mp4"],
        ids=["video_stream", "audio_stream", "merge_output"],
    )
    def test_find_by_id_ignores_a_download_in_progress(self, tmp_path, piece):
        (tmp_path / piece).touch()
        assert SongList().find_by_id(str(tmp_path), VIDEO_ID) is None

    def test_find_by_id_finds_the_finished_song_beside_its_pieces(self, tmp_path):
        (tmp_path / f"Song---{VIDEO_ID}.f137.mp4").touch()
        (tmp_path / f"Song---{VIDEO_ID}.mp4").touch()
        found = SongList().find_by_id(str(tmp_path), VIDEO_ID)
        assert found == str(tmp_path / f"Song---{VIDEO_ID}.mp4")

    def test_scan_skips_pieces_and_sync_conflicts(self, tmp_path):
        names = [
            f"Song---{VIDEO_ID}.mp4",
            f"Song---{VIDEO_ID}.f137.mp4",
            f"Song---{VIDEO_ID}.temp.mp4",
            f"Song---{VIDEO_ID}.sync-conflict-20261103-120000-ABCDEFG.mp4",
            "Hand Added.mp3",
        ]
        for name in names:
            (tmp_path / name).touch()

        found = LibraryScanner(MagicMock())._walk_disk(str(tmp_path))

        assert {os.path.basename(p) for p in found} == {f"Song---{VIDEO_ID}.mp4", "Hand Added.mp3"}


# --------------------------------------------------------------------------
# One download per video, across servers
# --------------------------------------------------------------------------


@pytest.fixture
def manager(tmp_path):
    song_manager = MagicMock()
    song_manager.songs = SongList()  # real: it looks at the folder
    return DownloadManager(
        events=EventSystem(),
        preferences=PreferenceManager(),
        song_manager=song_manager,
        queue_manager=MagicMock(),
        download_path=str(tmp_path),
    )


def _lock(tmp_path):
    return tmp_path / f".pikaraoke-downloading-{VIDEO_ID}"


def _song(tmp_path):
    return tmp_path / f"Song---{VIDEO_ID}.mp4"


@patch("flask_babel._", side_effect=lambda x: x)
@patch("pikaraoke.lib.download_manager.build_ytdl_download_command", return_value=["yt-dlp"])
class TestDownloadLock:
    def test_holds_the_lock_while_downloading(self, _cmd, _gettext, manager, tmp_path):
        seen = []

        def download(cmd, url):
            seen.append(_lock(tmp_path).exists())
            _song(tmp_path).touch()
            return 0, ""

        manager._run_download = download

        assert manager._execute_download(URL, False, "Alex", "Song") == 0
        assert seen == [True]
        assert not _lock(tmp_path).exists()

    def test_releases_the_lock_when_the_download_blows_up(self, _cmd, _gettext, manager, tmp_path):
        manager._run_download = MagicMock(side_effect=RuntimeError("yt-dlp vanished"))

        with pytest.raises(RuntimeError):
            manager._execute_download(URL, False, "Alex", "Song")

        assert not _lock(tmp_path).exists()

    def test_waits_for_another_server_then_uses_its_file(self, _cmd, _gettext, manager, tmp_path):
        _lock(tmp_path).touch()

        def other_server_finishes(_seconds):
            _song(tmp_path).touch()
            _lock(tmp_path).unlink()

        manager._run_download = MagicMock()
        with patch("pikaraoke.lib.download_manager.time.sleep", side_effect=other_server_finishes):
            rc = manager._execute_download(URL, True, "Alex", "Song", device_id="phone-1")

        assert rc == 0
        manager._run_download.assert_not_called()
        # Treated exactly like a finished download: queued, and owned by who asked.
        manager._queue_manager.enqueue.assert_called_once_with(
            str(_song(tmp_path)), "Alex", log_action=False, device_id="phone-1"
        )
        assert not _lock(tmp_path).exists()

    def test_downloads_itself_when_the_other_server_fails(self, _cmd, _gettext, manager, tmp_path):
        _lock(tmp_path).touch()
        manager._run_download = MagicMock(return_value=(0, ""))

        with patch(
            "pikaraoke.lib.download_manager.time.sleep",
            side_effect=lambda _s: _lock(tmp_path).unlink(),
        ):
            manager._execute_download(URL, False, "Alex", "Song")

        manager._run_download.assert_called_once()

    def test_takes_over_a_lock_abandoned_by_a_dead_server(self, _cmd, _gettext, manager, tmp_path):
        _lock(tmp_path).touch()
        long_ago = time.time() - DOWNLOAD_LOCK_STALE_SECONDS - 60
        os.utime(_lock(tmp_path), (long_ago, long_ago))
        manager._run_download = MagicMock(return_value=(0, ""))

        with patch("pikaraoke.lib.download_manager.time.sleep") as sleep:
            manager._execute_download(URL, False, "Alex", "Song")

        sleep.assert_not_called()
        manager._run_download.assert_called_once()
        assert not _lock(tmp_path).exists()

    def test_skips_a_song_already_on_disk(self, _cmd, _gettext, manager, tmp_path):
        """Two guests here asked for the same new song; the second finds the first's."""
        _song(tmp_path).touch()
        manager._run_download = MagicMock()

        assert manager._execute_download(URL, False, "Alex", "Song") == 0
        manager._run_download.assert_not_called()

    def test_downloads_unguarded_when_the_folder_takes_no_lock(self, _cmd, _gettext, tmp_path):
        missing = DownloadManager(
            events=EventSystem(),
            preferences=PreferenceManager(),
            song_manager=MagicMock(songs=SongList()),
            queue_manager=MagicMock(),
            download_path=str(tmp_path / "not-there"),
        )
        missing._run_download = MagicMock(return_value=(1, "ERROR: can't write"))

        missing._execute_download(URL, False, "Alex", "Song")

        missing._run_download.assert_called_once()


def test_progress_keeps_the_lock_fresh(manager, tmp_path):
    _lock(tmp_path).touch()
    long_ago = time.time() - 120
    os.utime(_lock(tmp_path), (long_ago, long_ago))
    manager._download_lock = str(_lock(tmp_path))

    process = MagicMock()
    process.stdout.readline.side_effect = ["[download]  50.0% of 4MiB at 1MiB/s ETA 00:02\n", ""]
    process.poll.return_value = 0
    with patch("subprocess.Popen", return_value=process):
        manager._run_download(["yt-dlp"], URL)

    assert time.time() - os.path.getmtime(_lock(tmp_path)) < 60


# --------------------------------------------------------------------------
# Noticing songs another server added
# --------------------------------------------------------------------------


@pytest.fixture
def karaoke():
    k = Karaoke.__new__(Karaoke)
    k.events = MagicMock()
    k.db = MagicMock()
    k.song_manager = MagicMock()
    k.download_path = "/songs"
    k._sync_lock = threading.Lock()
    k._scanner = MagicMock()
    return k


class TestScheduledRescan:
    def test_rescans_once_the_interval_has_passed(self, karaoke):
        karaoke.sync_library = MagicMock()
        karaoke._last_library_rescan = time.monotonic() - karaoke.library_rescan_interval - 1

        karaoke._rescan_library_if_due()
        karaoke._rescan_library_if_due()  # straight after: not due again yet

        karaoke.sync_library.assert_called_once_with(quiet=True)

    def test_not_before_the_interval(self, karaoke):
        karaoke.sync_library = MagicMock()
        karaoke._last_library_rescan = time.monotonic()

        karaoke._rescan_library_if_due()

        karaoke.sync_library.assert_not_called()

    def test_runs_from_the_main_loop(self, karaoke):
        karaoke._rescan_library_if_due = MagicMock()
        karaoke.loop_interval = 0

        karaoke.handle_run_loop()

        karaoke._rescan_library_if_due.assert_called_once()

    def test_a_quiet_scan_adds_songs_without_telling_every_phone(self, karaoke):
        karaoke._scanner.scan.return_value = ScanResult(
            added=1, moved=0, deleted=0, circuit_tripped=False
        )
        karaoke.db.get_all_song_paths.return_value = ["/songs/New---dQw4w9WgXcQ.mp4"]

        with patch("pikaraoke.karaoke.threading.Thread") as thread:
            assert karaoke.sync_library(quiet=True)
        target, args = thread.call_args.kwargs["target"], thread.call_args.kwargs["args"]
        target(*args)

        karaoke.song_manager.songs.update.assert_called_once_with(["/songs/New---dQw4w9WgXcQ.mp4"])
        karaoke.events.emit.assert_not_called()
        assert not karaoke._sync_lock.locked()

    def test_sync_now_still_reports(self, karaoke):
        karaoke._scanner.scan.return_value = ScanResult(
            added=1, moved=0, deleted=0, circuit_tripped=False
        )
        karaoke.db.get_all_song_paths.return_value = ["/songs/New---dQw4w9WgXcQ.mp4"]

        with patch("pikaraoke.karaoke.threading.Thread") as thread:
            karaoke.sync_library()
        thread.call_args.kwargs["target"](*thread.call_args.kwargs["args"])

        emitted = [c.args[0] for c in karaoke.events.emit.call_args_list]
        assert emitted == ["sync_started", "notification", "sync_finished"]

    def test_a_scheduled_scan_waits_out_a_sync_already_running(self, karaoke):
        karaoke._sync_lock.acquire()
        with patch("pikaraoke.karaoke.threading.Thread") as thread:
            assert karaoke.sync_library(quiet=True) is False
        thread.assert_not_called()
