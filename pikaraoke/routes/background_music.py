"""Background music streaming routes."""

import os
import random
import urllib

import flask_babel
from flask import abort, jsonify, send_file, url_for
from flask_smorest import Blueprint

from pikaraoke.lib.current_app import get_karaoke_instance

_ = flask_babel.gettext

background_music_bp = Blueprint("bg_music", __name__)


def create_randomized_playlist(input_directory, base_url, max_songs=50):
    # Get all mp3 files in the given directory
    files = [
        f
        for f in os.listdir(input_directory)
        if f.lower().endswith(".mp3") or f.lower().endswith(".mp4")
    ]

    # Shuffle the list of mp3 files
    random.shuffle(files)
    files = files[:max_songs]

    # Create the playlist
    playlist = []
    for mp3 in files:
        mp3 = urllib.parse.quote(mp3.encode("utf8"))
        url = f"{base_url}/{mp3}"
        playlist.append(f"{url}")

    return playlist


@background_music_bp.route("/bg_music/<file>", methods=["GET"])
def bg_music(file):
    """Stream a background music file."""
    k = get_karaoke_instance()
    real_bg_music_path = os.path.realpath(k.bg_music_path)
    mp3_path = os.path.realpath(os.path.join(real_bg_music_path, file))
    try:
        within_bg_music_path = (
            os.path.commonpath([real_bg_music_path, mp3_path]) == real_bg_music_path
        )
    except ValueError:
        # Raised on Windows when the paths are on different drives.
        within_bg_music_path = False
    if not within_bg_music_path or not os.path.isfile(mp3_path):
        abort(404)
    return send_file(mp3_path, mimetype="audio/mpeg")


@background_music_bp.route("/bg_playlist", methods=["GET"])
def bg_playlist():
    """Get a randomized background music playlist."""
    k = get_karaoke_instance()
    if (k.bg_music_path == None) or (not os.path.exists(k.bg_music_path)):
        return jsonify([])
    base_url = url_for("bg_music.bg_music", file="").rstrip("/")
    playlist = create_randomized_playlist(k.bg_music_path, base_url, 50)
    return jsonify(playlist)
