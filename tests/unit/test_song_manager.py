"""Unit tests for SongManager."""

import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pikaraoke.lib.library_scanner import LibraryScanner
from pikaraoke.lib.song_manager import SongManager


def _native(path: Path) -> str:
    """Convert Path to native OS string to match SongList's internal storage format."""
    return str(path)


@pytest.fixture
def mock_db():
    return MagicMock()


class TestFilenameFromPath:
    """Tests for the filename_from_path static method."""

    def test_basic(self):
        assert SongManager.filename_from_path("/songs/My Song.mp4") == "My Song"

    def test_with_youtube_id(self):
        result = SongManager.filename_from_path("/songs/Artist - Song Title---dQw4w9WgXcQ.mp4")
        assert result == "Artist - Song Title"

    def test_keep_youtube_id(self):
        result = SongManager.filename_from_path(
            "/songs/Artist - Song---dQw4w9WgXcQ.mp4", remove_youtube_id=False
        )
        assert result == "Artist - Song---dQw4w9WgXcQ"

    def test_nested_directory(self):
        result = SongManager.filename_from_path(
            "/home/user/music/karaoke/songs/Track---dQw4w9WgXcQ.mp4"
        )
        assert result == "Track"

    def test_multiple_dashes(self):
        result = SongManager.filename_from_path(
            "/songs/Artist - Song - Live Version---dQw4w9WgXcQ.mp4"
        )
        assert result == "Artist - Song - Live Version"

    def test_no_extension(self):
        assert SongManager.filename_from_path("/songs/SongName") == "SongName"

    def test_cdg_zip(self):
        """CDG+ZIP files have no YouTube ID, so the name is returned as-is."""
        assert SongManager.filename_from_path("/songs/Karaoke Track.zip") == "Karaoke Track"

    def test_bracket_format_youtube_id(self):
        result = SongManager.filename_from_path("/songs/Artist - Song [dQw4w9WgXcQ].mp4")
        assert result == "Artist - Song"

    def test_bracket_format_keep_id(self):
        result = SongManager.filename_from_path(
            "/songs/Artist - Song [dQw4w9WgXcQ].mp4", remove_youtube_id=False
        )
        assert result == "Artist - Song [dQw4w9WgXcQ]"

    def test_bracket_format_short_id_not_stripped(self):
        """Non-YouTube files are not tidied, so short bracket text is preserved."""
        result = SongManager.filename_from_path("/songs/Song [short].mp4")
        assert result == "Song [short]"

    # --- regex_tidy integration: noise word stripping ---

    def test_strips_karaoke_noise_words(self):
        result = SongManager.filename_from_path(
            "/songs/Queen - Bohemian Rhapsody Karaoke Version HD---dQw4w9WgXcQ.mp4"
        )
        assert result == "Queen - Bohemian Rhapsody"

    def test_strips_instrumental_suffix(self):
        result = SongManager.filename_from_path(
            "/songs/Artist - Song Instrumental---dQw4w9WgXcQ.mp4"
        )
        assert result == "Artist - Song"

    def test_strips_lyrics_suffix(self):
        result = SongManager.filename_from_path(
            "/songs/Artist - Song With Lyrics---dQw4w9WgXcQ.mp4"
        )
        assert result == "Artist - Song"

    def test_underscores_replaced_with_spaces(self):
        result = SongManager.filename_from_path("/songs/Artist_-_Song_Title---dQw4w9WgXcQ.mp4")
        assert result == "Artist - Song Title"

    def test_all_noise_fallback_preserves_original(self):
        """When regex_tidy strips everything, fall back to the pre-tidy name."""
        result = SongManager.filename_from_path("/songs/Karaoke Track---dQw4w9WgXcQ.mp4")
        assert result == "Karaoke Track"

    def test_tidy_not_applied_when_keeping_youtube_id(self):
        """remove_youtube_id=False skips tidying (used by batch renamer for raw stems)."""
        result = SongManager.filename_from_path(
            "/songs/Artist - Song_Title Karaoke---dQw4w9WgXcQ.mp4",
            remove_youtube_id=False,
        )
        assert result == "Artist - Song_Title Karaoke---dQw4w9WgXcQ"


class TestDelete:
    def test_removes_file_and_updates_songs(self, tmp_path, mock_db):
        song = tmp_path / "Test---abc.mp4"
        song.write_text("fake")
        sm = SongManager(str(tmp_path), db=mock_db)
        sm.songs.add_if_valid(_native(song))
        sm.delete(_native(song))
        assert not song.exists()
        assert len(sm.songs) == 0

    def test_deletes_cdg_companion(self, tmp_path, mock_db):
        song = tmp_path / "Test---abc.mp4"
        cdg = tmp_path / "Test---abc.cdg"
        song.write_text("fake")
        cdg.write_text("fake")
        sm = SongManager(str(tmp_path), db=mock_db)
        sm.songs.add_if_valid(_native(song))
        sm.delete(_native(song))
        assert not cdg.exists()

    def test_deletes_ass_companion(self, tmp_path, mock_db):
        song = tmp_path / "Test---abc.mp4"
        ass = tmp_path / "Test---abc.ass"
        song.write_text("fake")
        ass.write_text("fake")
        sm = SongManager(str(tmp_path), db=mock_db)
        sm.songs.add_if_valid(_native(song))
        sm.delete(_native(song))
        assert not ass.exists()

    def test_nonexistent_file_no_error(self, tmp_path, mock_db):
        sm = SongManager(str(tmp_path), db=mock_db)
        sm.delete(_native(tmp_path / "nonexistent.mp4"))

    def test_refuses_to_delete_path_outside_download_path(self, tmp_path, mock_db):
        outside_dir = tmp_path.parent / "outside_song_manager_test"
        outside_dir.mkdir(exist_ok=True)
        outside_file = outside_dir / "not-a-song.txt"
        outside_file.write_text("should survive")
        library = tmp_path / "library"
        library.mkdir()
        sm = SongManager(str(library), db=mock_db)

        sm.delete(_native(outside_file))

        assert outside_file.exists()
        mock_db.delete_by_path.assert_not_called()

    def test_refuses_to_delete_traversal_path(self, tmp_path, mock_db):
        library = tmp_path / "library"
        library.mkdir()
        escaped = tmp_path / "escaped.txt"
        escaped.write_text("should survive")
        sm = SongManager(str(library), db=mock_db)

        sm.delete(_native(library / ".." / "escaped.txt"))

        assert escaped.exists()


class TestRename:
    def test_renames_file_and_updates_songs(self, tmp_path, mock_db):
        song = tmp_path / "Old Name---abc.mp4"
        song.write_text("fake")
        sm = SongManager(str(tmp_path), db=mock_db)
        sm.songs.add_if_valid(_native(song))
        sm.rename(_native(song), "New Name---abc")
        assert not song.exists()
        assert (tmp_path / "New Name---abc.mp4").exists()

    def test_renames_cdg_companion(self, tmp_path, mock_db):
        song = tmp_path / "Old---abc.mp4"
        cdg = tmp_path / "Old---abc.cdg"
        song.write_text("fake")
        cdg.write_text("fake")
        sm = SongManager(str(tmp_path), db=mock_db)
        sm.songs.add_if_valid(_native(song))
        sm.rename(_native(song), "New---abc")
        assert (tmp_path / "New---abc.cdg").exists()
        assert not cdg.exists()

    def test_renames_ass_companion(self, tmp_path, mock_db):
        song = tmp_path / "Old---abc.mp4"
        ass = tmp_path / "Old---abc.ass"
        song.write_text("fake")
        ass.write_text("fake")
        sm = SongManager(str(tmp_path), db=mock_db)
        sm.songs.add_if_valid(_native(song))
        sm.rename(_native(song), "New---abc")
        assert (tmp_path / "New---abc.ass").exists()
        assert not ass.exists()

    def test_returns_new_path(self, tmp_path, mock_db):
        song = tmp_path / "Old---abc.mp4"
        song.write_text("fake")
        sm = SongManager(str(tmp_path), db=mock_db)
        sm.songs.add_if_valid(_native(song))
        result = sm.rename(_native(song), "New---abc")
        assert result == _native(tmp_path / "New---abc.mp4")

    def test_refuses_to_rename_path_outside_download_path(self, tmp_path, mock_db):
        outside_dir = tmp_path.parent / "outside_song_manager_rename_test"
        outside_dir.mkdir(exist_ok=True)
        outside_file = outside_dir / "not-a-song.txt"
        outside_file.write_text("should survive")
        library = tmp_path / "library"
        library.mkdir()
        sm = SongManager(str(library), db=mock_db)

        with pytest.raises(OSError):
            sm.rename(_native(outside_file), "New---abc")

        assert outside_file.exists()


class TestDBCoordination:
    """Tests that SongManager coordinates with KaraokeDatabase when provided."""

    def test_delete_calls_db_delete(self, tmp_path):
        song = tmp_path / "Test---abc.mp4"
        song.write_text("fake")
        mock_db = MagicMock()
        sm = SongManager(str(tmp_path), db=mock_db)
        sm.songs.add_if_valid(_native(song))
        sm.delete(_native(song))
        mock_db.delete_by_path.assert_called_once_with(_native(song))

    def test_rename_calls_db_update_path(self, tmp_path):
        song = tmp_path / "Old---abc.mp4"
        song.write_text("fake")
        mock_db = MagicMock()
        sm = SongManager(str(tmp_path), db=mock_db)
        sm.songs.add_if_valid(_native(song))
        sm.rename(_native(song), "New---abc")
        mock_db.update_path.assert_called_once_with(
            _native(song), _native(tmp_path / "New---abc.mp4")
        )

    def test_register_download_adds_to_songs_and_db(self, tmp_path):
        song = tmp_path / "New---xyz12345678.mp4"
        song.write_text("fake")
        mock_db = MagicMock()
        sm = SongManager(str(tmp_path), db=mock_db)
        sm.register_download(_native(song))
        assert _native(song) in sm.songs
        mock_db.insert_songs.assert_called_once()


class TestTypedNames:
    """Names typed on the Edit Song page are shown exactly as typed."""

    GUIDE = "Yuuri - Betelgeuse (Romaji Karaoke with Guide Melody)---aaaaaaaaaaa"
    NO_GUIDE = "Yuuri - Betelgeuse (No Guide Melody)---bbbbbbbbbbb"

    def _manager(self, folder, mock_db):
        return SongManager(str(folder), db=mock_db, get_title_tidy=lambda: True)

    def _song(self, folder, sm, stem):
        song = folder / f"{stem}.mp4"
        song.write_text("fake")
        sm.songs.add_if_valid(_native(song))
        return song

    def test_typed_name_skips_title_cleanup(self, tmp_path, mock_db):
        sm = self._manager(tmp_path, mock_db)
        song = self._song(tmp_path, sm, "Yuuri - Betelgeuse---bbbbbbbbbbb")
        new_path = sm.rename(_native(song), self.NO_GUIDE, typed_by_hand=True)
        assert sm.display_name_from_path(new_path) == "Yuuri - Betelgeuse (No Guide Melody)"

    def test_other_songs_are_still_cleaned_up(self, tmp_path, mock_db):
        sm = self._manager(tmp_path, mock_db)
        typed = self._song(tmp_path, sm, "Something---ccccccccccc")
        sm.rename(_native(typed), self.NO_GUIDE, typed_by_hand=True)
        untouched = self._song(tmp_path, sm, self.GUIDE)
        assert sm.display_name_from_path(_native(untouched)) == "Yuuri - Betelgeuse"

    def test_rename_by_other_means_leaves_the_name_to_cleanup(self, tmp_path, mock_db):
        sm = self._manager(tmp_path, mock_db)
        song = self._song(tmp_path, sm, "Old---bbbbbbbbbbb")
        new_path = sm.rename(_native(song), self.NO_GUIDE)
        assert sm.display_name_from_path(new_path) == "Yuuri - Betelgeuse"

    def test_another_server_sharing_the_folder_sees_it(self, tmp_path, mock_db):
        sm = self._manager(tmp_path, mock_db)
        other = self._manager(tmp_path, mock_db)
        # The other server has already read the (empty) list once.
        assert other.display_name_from_path(_native(tmp_path / f"{self.GUIDE}.mp4")) == (
            "Yuuri - Betelgeuse"
        )
        song = self._song(tmp_path, sm, "Old---aaaaaaaaaaa")
        new_path = sm.rename(_native(song), self.GUIDE, typed_by_hand=True)
        assert other.display_name_from_path(new_path) == (
            "Yuuri - Betelgeuse (Romaji Karaoke with Guide Melody)"
        )

    def test_renaming_a_typed_song_again_keeps_it_as_typed(self, tmp_path, mock_db):
        sm = self._manager(tmp_path, mock_db)
        song = self._song(tmp_path, sm, "Old---bbbbbbbbbbb")
        typed = sm.rename(_native(song), self.NO_GUIDE, typed_by_hand=True)
        renamed = sm.rename(typed, "Yuuri - Betelgeuse (Off Vocal)---bbbbbbbbbbb")
        assert sm.display_name_from_path(renamed) == "Yuuri - Betelgeuse (Off Vocal)"
        names = (tmp_path / ".pikaraoke-typed-names").read_text(encoding="utf-8").splitlines()
        assert names == ["Yuuri - Betelgeuse (Off Vocal)---bbbbbbbbbbb"]

    def test_delete_forgets_the_name(self, tmp_path, mock_db):
        sm = self._manager(tmp_path, mock_db)
        song = self._song(tmp_path, sm, "Old---bbbbbbbbbbb")
        typed = sm.rename(_native(song), self.NO_GUIDE, typed_by_hand=True)
        sm.delete(typed)
        assert (tmp_path / ".pikaraoke-typed-names").read_text(encoding="utf-8") == ""

    def test_never_writes_into_a_hard_linked_copy(self, tmp_path, mock_db):
        # testkar's song folder hard-links production's files.
        production = tmp_path / "production"
        test = tmp_path / "test"
        production.mkdir()
        test.mkdir()
        (production / ".pikaraoke-typed-names").write_text(f"{self.GUIDE}\n", encoding="utf-8")
        os.link(production / ".pikaraoke-typed-names", test / ".pikaraoke-typed-names")

        sm = self._manager(test, mock_db)
        song = self._song(test, sm, "Old---bbbbbbbbbbb")
        sm.rename(_native(song), self.NO_GUIDE, typed_by_hand=True)

        assert (production / ".pikaraoke-typed-names").read_text(encoding="utf-8") == (
            f"{self.GUIDE}\n"
        )

    def test_typed_names_file_is_not_a_song(self, tmp_path, mock_db):
        sm = self._manager(tmp_path, mock_db)
        song = self._song(tmp_path, sm, "Old---bbbbbbbbbbb")
        sm.rename(_native(song), self.NO_GUIDE, typed_by_hand=True)
        scanner = LibraryScanner(mock_db)
        assert scanner._walk_disk(str(tmp_path)) == {_native(tmp_path / f"{self.NO_GUIDE}.mp4")}

    def test_keep_name_as_typed_without_renaming(self, tmp_path, mock_db):
        sm = self._manager(tmp_path, mock_db)
        song = self._song(tmp_path, sm, self.NO_GUIDE)
        sm.keep_name_as_typed(_native(song))
        assert song.exists()
        assert sm.display_name_from_path(_native(song)) == "Yuuri - Betelgeuse (No Guide Melody)"
