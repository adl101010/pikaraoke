"""The run loop drives the main thread, so an exception escaping it exits the
interpreter and kills the whole container. These tests pin that it can't."""

from queue import Empty, Queue
from unittest.mock import MagicMock

import pytest

from pikaraoke.karaoke import Karaoke
from pikaraoke.lib.stream_manager import StreamManager


@pytest.fixture
def karaoke():
    """A Karaoke with the run loop's collaborators stubbed out."""
    k = Karaoke.__new__(Karaoke)
    k.running = True
    k.loop_interval = 100
    k.queue_manager = MagicMock()
    k.queue_manager.queue = []
    k.playback_controller = MagicMock()
    k.playback_controller.is_playing = False
    k.playback_controller.now_playing = None
    k.db = MagicMock()
    k.preferences = MagicMock()
    k.preferences.get_or_default.return_value = 0
    k.events = MagicMock()
    k.url = "http://localhost:5555"
    return k


def _stop_after_one_pass(k):
    """Let the loop run a single iteration, then ask it to stop."""

    def handle():
        k.running = False

    k.handle_run_loop = handle


class TestRunLoopSurvivesFailures:
    def test_playback_error_does_not_escape_the_loop(self, karaoke):
        karaoke.queue_manager.queue = [{"file": "/songs/a.mp4", "user": "Alex", "semitones": 0}]
        karaoke.queue_manager.pop_next.return_value = {
            "file": "/songs/a.mp4",
            "user": "Alex",
            "semitones": 0,
        }
        karaoke.playback_controller.play_file.side_effect = RuntimeError("ffmpeg exploded")
        _stop_after_one_pass(karaoke)

        karaoke.run()  # must return, not raise

        karaoke.playback_controller.end_song.assert_called_once()

    def test_recording_a_play_failing_does_not_escape(self, karaoke):
        karaoke.queue_manager.queue = [{"file": "/songs/a.mp4", "user": "Alex", "semitones": 0}]
        karaoke.queue_manager.pop_next.return_value = {
            "file": "/songs/a.mp4",
            "user": "Alex",
            "semitones": 0,
        }
        karaoke.playback_controller.play_file.return_value = MagicMock(success=True, error=None)
        karaoke.db.record_play.side_effect = OSError("database is locked")
        _stop_after_one_pass(karaoke)

        karaoke.run()

        karaoke.playback_controller.end_song.assert_called_once()

    def test_failure_while_cleaning_up_still_does_not_escape(self, karaoke):
        """Even the recovery path failing must not take the process down."""
        karaoke.playback_controller.log_output.side_effect = RuntimeError("boom")
        karaoke.playback_controller.end_song.side_effect = RuntimeError("cleanup failed too")
        _stop_after_one_pass(karaoke)

        karaoke.run()

        # Flags forced back by hand, so the next song can still start.
        assert karaoke.playback_controller.is_playing is False
        assert karaoke.playback_controller.now_playing is None

    def test_keyboard_interrupt_still_stops_the_loop(self, karaoke):
        karaoke.playback_controller.log_output.side_effect = KeyboardInterrupt()

        karaoke.run()

        assert karaoke.running is False
        karaoke.playback_controller.end_song.assert_not_called()


class TestFfmpegLogDraining:
    def _manager(self):
        return StreamManager.__new__(StreamManager)

    def test_no_queue_is_a_no_op(self):
        sm = self._manager()
        sm.ffmpeg_log = None
        sm.log_ffmpeg_output()

    def test_drains_pending_output(self):
        sm = self._manager()
        sm.ffmpeg_log = Queue()
        sm.ffmpeg_log.put(b"frame= 1234 fps=30")
        sm.log_ffmpeg_output()
        assert sm.ffmpeg_log.qsize() == 0

    def test_survives_a_competing_consumer_emptying_the_queue(self):
        """qsize() said non-empty, but the item is gone by the time we get it."""

        class Drained(Queue):
            def qsize(self):
                return 1  # always claims to have something

            def get_nowait(self):
                raise Empty

        sm = self._manager()
        sm.ffmpeg_log = Drained()

        sm.log_ffmpeg_output()  # must return rather than raise Empty

    def test_uses_one_queue_even_if_it_is_swapped_mid_drain(self):
        """Starting the next song rebinds ffmpeg_log; the drain must not follow it."""
        sm = self._manager()
        original = Queue()
        original.put(b"line one")

        class Swapping(Queue):
            def get_nowait(self):
                sm.ffmpeg_log = Queue()  # simulate the next song starting
                return super().get_nowait()

        swapping = Swapping()
        swapping.put(b"line one")
        sm.ffmpeg_log = swapping

        sm.log_ffmpeg_output()  # must not raise

        assert swapping.qsize() == 0
