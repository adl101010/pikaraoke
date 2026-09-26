"""YouTube search and download routes."""

from __future__ import annotations

import json
import os

import flask_babel
from flask import current_app, jsonify, render_template, request, url_for
from flask_smorest import Blueprint
from marshmallow import Schema, fields

from pikaraoke.lib.current_app import (
    get_client_ip,
    get_device_id,
    get_karaoke_instance,
    get_site_name,
)
from pikaraoke.lib.metadata_parser import search_matches, searchable_song_text
from pikaraoke.lib.youtube_dl import (
    get_search_results,
    get_stream_url,
    get_youtube_id_from_url,
)

_ = flask_babel.gettext

search_bp = Blueprint("search", __name__)


class AutocompleteQuery(Schema):
    q = fields.String(required=True, metadata={"description": "Search query for autocomplete"})


class PreviewQuery(Schema):
    url = fields.String(required=True, metadata={"description": "YouTube video URL to preview"})


class DownloadBody(Schema):
    song_url = fields.String(required=True, metadata={"description": "YouTube URL to download"})
    song_added_by = fields.String(
        required=True, metadata={"description": "Name of the user requesting the download"}
    )
    song_title = fields.String(
        required=True, metadata={"description": "Display title for the song"}
    )
    queue = fields.Boolean(
        load_default=False, metadata={"description": "Whether to queue the song after download"}
    )


@search_bp.route("/search", methods=["GET"])
def search():
    """YouTube search page."""
    k = get_karaoke_instance()
    site_name = get_site_name()
    search_string = request.args.get("search_string")
    if search_string:
        non_karaoke = request.args.get("non_karaoke") == "true"
        if non_karaoke:
            search_results = get_search_results(search_string)
        else:
            search_results = get_search_results(search_string + " karaoke")
    else:
        search_string = None
        search_results = None
    return render_template(
        "search.html",
        site_title=site_name,
        title="Search",
        songs=k.song_manager.songs,
        search_results=search_results,
        search_string=search_string,
    )


@search_bp.route("/autocomplete")
@search_bp.arguments(AutocompleteQuery, location="query")
def autocomplete(query):
    """Search available songs for autocomplete."""
    k = get_karaoke_instance()
    q = query["q"]
    result = []
    for each in k.song_manager.songs:
        if search_matches(q, searchable_song_text(each)):
            result.append(
                {
                    "path": each,
                    "fileName": k.song_manager.display_name_from_path(each),
                    "type": "autocomplete",
                }
            )
    response = current_app.response_class(response=json.dumps(result), mimetype="application/json")
    return response


@search_bp.route("/preview")
@search_bp.arguments(PreviewQuery, location="query")
def preview(query):
    """Get a direct stream URL for previewing a YouTube video."""
    stream_url = get_stream_url(query["url"])
    if stream_url is None:
        return jsonify({"error": "Could not fetch stream URL"}), 500
    return jsonify({"stream_url": stream_url})


@search_bp.route("/download", methods=["POST"])
@search_bp.arguments(DownloadBody, location="json")
def download(form):
    """Download a video from YouTube."""
    k = get_karaoke_instance()
    song = form["song_url"]
    user = form["song_added_by"]
    title = form["song_title"]
    queue = form.get("queue", False)

    existing = _library_copy_of(k, song)
    if existing is not None:
        return _use_existing_copy(k, existing, user, queue)

    # Queue the download (processed serially by the download worker)
    k.download_manager.queue_download(song, queue, user, title, ip_address=get_client_ip())

    return jsonify({"status": "ok"})


def _library_copy_of(k, song_url: str) -> str | None:
    """The path of an already-downloaded copy of this video, if we have one.

    Guests search YouTube rather than the library, so the same popular song
    gets requested over and over. Downloading it again costs the guest a wait
    for a file we already have, and leaves a near-duplicate behind.
    """
    video_id = get_youtube_id_from_url(song_url)
    if not video_id:
        return None
    existing = k.db.get_song_by_youtube_id(video_id)
    # A row can outlive its file if it was deleted outside the app. Falling
    # through to a real download beats queueing a song that can't play.
    if existing and os.path.isfile(existing):
        return existing
    return None


def _use_existing_copy(k, song_path: str, user: str, queue: bool):
    """Queue (or just report) a song the library already holds."""
    title = k.song_manager.display_name_from_path(song_path, True)
    if not queue:
        k.events.emit(
            "notification",
            # MSG: Shown when a guest downloads a song the library already has.
            _("Already in the library: %s") % title,
            "info",
        )
        return jsonify({"status": "already_downloaded", "queued": False})

    # enqueue() raises its own notification, including when it refuses --
    # a full queue or a song already waiting both need saying out loud.
    added, message = k.queue_manager.enqueue(song_path, user, device_id=get_device_id())
    if not added:
        k.events.emit("notification", message, "danger")
    return jsonify({"status": "already_downloaded", "queued": bool(added)})
