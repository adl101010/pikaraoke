"""Song library management: scan, delete, rename, and display name operations."""

import contextlib
import logging
import os
import re
from collections.abc import Callable

from pikaraoke.lib.ffmpeg import get_media_duration
from pikaraoke.lib.get_platform import is_windows
from pikaraoke.lib.karaoke_database import KaraokeDatabase
from pikaraoke.lib.library_scanner import build_song_record
from pikaraoke.lib.metadata_parser import regex_tidy, youtube_id_suffix
from pikaraoke.lib.song_list import SongList

# Characters illegal in Windows filenames
_WINDOWS_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*]')

# Names someone typed on the Edit Song page, one filename (without extension)
# per line. Title cleanup leaves these alone: "(No Guide Melody)" is what tells
# two videos of the same song apart. Kept in the song folder rather than the
# database so every server sharing the folder sees them.
TYPED_NAMES_FILE = ".pikaraoke-typed-names"


def sanitize_filename(name: str) -> str:
    """Remove characters that are illegal in filenames on the current platform."""
    if is_windows():
        name = _WINDOWS_ILLEGAL_CHARS.sub("-", name)
    return name.strip()


def _stem(file_path: str) -> str:
    return os.path.splitext(os.path.basename(file_path))[0]


class SongManager:
    """Manages the song library and file operations.

    Owns the SongList instance and provides all song discovery,
    delete, rename, and display name operations.
    """

    def __init__(
        self,
        download_path: str,
        db: KaraokeDatabase,
        get_title_tidy: Callable[[], bool] | None = None,
    ) -> None:
        self.download_path = download_path
        self.songs = SongList()
        self._db = db
        self._get_title_tidy = get_title_tidy
        self._typed_names_cache: tuple[tuple[int, int], frozenset[str]] | None = None

    @staticmethod
    def filename_from_path(
        file_path: str, remove_youtube_id: bool = True, tidy: bool = True
    ) -> str:
        """Extract a display name from a file path.

        Args:
            file_path: Full path to the file.
            remove_youtube_id: Strip YouTube ID suffix if present.
            tidy: Apply regex_tidy() to strip noise words and normalize.

        Returns:
            Filename without extension, optionally cleaned.
        """
        name = os.path.splitext(os.path.basename(file_path))[0]
        suffix = youtube_id_suffix(file_path)
        if remove_youtube_id and suffix:
            name = name[: -len(suffix)]
        if tidy and suffix and remove_youtube_id:
            tidied = regex_tidy(name)
            if tidied:
                name = tidied
        return name

    def display_name_from_path(self, file_path: str, remove_youtube_id: bool = True) -> str:
        """Extract display name from path, respecting the enable_title_tidy preference."""
        tidy = self._get_title_tidy() if self._get_title_tidy else True
        if tidy and _stem(file_path) in self._typed_names():
            tidy = False
        return self.filename_from_path(file_path, remove_youtube_id=remove_youtube_id, tidy=tidy)

    def _typed_names_path(self) -> str:
        return os.path.join(self.download_path, TYPED_NAMES_FILE)

    def _typed_names(self) -> frozenset[str]:
        """The names typed by hand, re-read only when another server changed them."""
        path = self._typed_names_path()
        try:
            stat = os.stat(path)
        except FileNotFoundError:
            return frozenset()
        version = (stat.st_mtime_ns, stat.st_size)
        if self._typed_names_cache and self._typed_names_cache[0] == version:
            return self._typed_names_cache[1]
        try:
            with open(path, encoding="utf-8") as f:
                names = frozenset(line.rstrip("\n") for line in f if line.strip())
        except OSError as e:
            logging.warning(f"Couldn't read {path}: {e}")
            return frozenset()
        self._typed_names_cache = (version, names)
        return names

    def _save_typed_names(self, names: frozenset[str]) -> None:
        # Written aside and swapped in, never edited in place: a test server's
        # song folder can hard-link production's files, and an in-place write
        # would change production's copy too.
        path = self._typed_names_path()
        temp_path = f"{path}.{os.getpid()}.tmp"
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                f.writelines(f"{name}\n" for name in sorted(names))
            os.replace(temp_path, path)
        except OSError as e:
            logging.warning(f"Couldn't save typed song names to {path}: {e}")
            with contextlib.suppress(OSError):
                os.remove(temp_path)

    def get_duration(self, file_path: str) -> int | None:
        """A song's length in seconds, measured once and then remembered.

        Reading it is cheap, but doing it on every request isn't free, and the
        queue asks about the same popular songs again and again -- so the first
        answer is saved on the song's own row.

        Returns None when the length isn't known, which callers must treat as
        "unknown" rather than zero.
        """
        saved = self._db.get_song_duration(file_path)
        if saved is not None:
            return saved
        # Zipped karaoke is only unpacked at play time, so probing the archive
        # would just fail. Its length is saved when it first plays instead.
        if os.path.splitext(file_path)[1].casefold() == ".zip":
            return None
        seconds = get_media_duration(file_path)
        if not seconds:
            return None
        self._db.set_song_duration(file_path, seconds)
        return seconds

    def remember_duration(self, file_path: str, seconds: int | None) -> None:
        """Save a length learned during playback, such as that of a zipped song."""
        if file_path and seconds:
            self._db.set_song_duration(file_path, seconds)

    def _is_within_download_path(self, path: str) -> bool:
        """Check a path resolves inside download_path, defeating '..'/symlink escapes."""
        real_download = os.path.realpath(self.download_path)
        real_path = os.path.realpath(path)
        try:
            return os.path.commonpath([real_download, real_path]) == real_download
        except ValueError:
            # Raised on Windows when the paths are on different drives.
            return False

    def _get_companion_files(self, song_path: str) -> list[str]:
        """Return paths to companion files (.cdg, .ass) that exist alongside a song."""
        dirpath = os.path.dirname(song_path)
        base = os.path.splitext(os.path.basename(song_path))[0]
        try:
            files = os.listdir(dirpath)
        except OSError:
            return []
        base_lower = base.lower()
        companions = []
        for f in files:
            f_base, f_ext = os.path.splitext(f)
            if f_base.lower() == base_lower and f_ext.lower() in (".cdg", ".ass"):
                companions.append(os.path.join(dirpath, f))
        return companions

    def delete(self, song_path: str) -> None:
        """Delete a song from disk, SongList, and DB."""
        if not self._is_within_download_path(song_path):
            logging.error(f"Refusing to delete path outside the song library: {song_path}")
            return
        logging.info(f"Deleting song: {song_path}")
        companions = self._get_companion_files(song_path)
        with contextlib.suppress(FileNotFoundError):
            os.remove(song_path)
        for companion in companions:
            with contextlib.suppress(FileNotFoundError):
                os.remove(companion)
        typed = self._typed_names()
        if _stem(song_path) in typed:
            self._save_typed_names(typed - {_stem(song_path)})
        self.songs.remove(song_path)
        self._db.delete_by_path(song_path)

    def rename(self, song_path: str, new_name: str, typed_by_hand: bool = False) -> str:
        """Rename a song on disk, in SongList, and in DB. Returns new path.

        Args:
            song_path: Full path to the current song file.
            new_name: New filename (without extension).
            typed_by_hand: Someone typed this name, so title cleanup must show
                it as is. A song already typed by hand keeps that either way.
        """
        if not self._is_within_download_path(song_path):
            raise OSError(f"Refusing to rename path outside the song library: {song_path}")
        new_name = sanitize_filename(new_name)
        logging.info(f"Renaming song: '{song_path}' to: {new_name}")
        companions = self._get_companion_files(song_path)
        _, ext = os.path.splitext(song_path)
        new_path = os.path.join(self.download_path, new_name + ext)
        os.rename(song_path, new_path)
        for companion in companions:
            companion_ext = os.path.splitext(companion)[1]
            os.rename(companion, os.path.join(self.download_path, new_name + companion_ext))
        self.songs.rename(song_path, new_path)
        self._db.update_path(song_path, new_path)
        typed = self._typed_names()
        old_stem = _stem(song_path)
        if typed_by_hand or old_stem in typed:
            self._save_typed_names((typed - {old_stem}) | {new_name})
        return new_path

    def register_download(self, song_path: str) -> None:
        """Register a newly downloaded song in SongList and DB."""
        self.songs.add_if_valid(song_path)
        self._db.insert_songs([build_song_record(song_path)])
