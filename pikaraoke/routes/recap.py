"""Tonight's recap: live and historical karaoke session summaries."""

import flask_babel
from flask import flash, jsonify, redirect, render_template, request, url_for
from flask_smorest import Blueprint
from marshmallow import Schema, fields

from pikaraoke.lib.current_app import get_karaoke_instance, get_site_name, is_admin
from pikaraoke.lib.session_stats import compute_all_sessions, is_session_live

_ = flask_babel.gettext

recap_bp = Blueprint("recap", __name__)


class SetSessionNameQuery(Schema):
    started_at = fields.String(
        required=True, metadata={"description": "started_at of the session to name"}
    )
    name = fields.String(
        load_default="", metadata={"description": "Name for the session (blank clears it)"}
    )


def _get_all_sessions():
    k = get_karaoke_instance()
    events = k.db.get_all_play_events()
    names = k.db.get_session_names()
    return compute_all_sessions(events, names=names)


def _song_list(session):
    k = get_karaoke_instance()
    return [
        {"display_name": k.song_manager.display_name_from_path(path), "count": count}
        for path, count in session.top_songs
    ]


def _songs_by_singer_display(session):
    k = get_karaoke_instance()
    return {
        singer: [
            {"display_name": k.song_manager.display_name_from_path(path), "count": count}
            for path, count in songs
        ]
        for singer, songs in session.songs_by_singer.items()
    }


@recap_bp.route("/recap")
def recap():
    """Recap page: defaults to the current/last session, or a specific past one via ?session=."""
    site_name = get_site_name()
    sessions = _get_all_sessions()

    requested_start = request.args.get("session")
    session = None
    if requested_start:
        session = next((s for s in sessions if s.started_at == requested_start), None)
    elif sessions:
        session = sessions[-1]

    is_latest = bool(sessions) and session is sessions[-1]
    live = is_latest and is_session_live(session) if session else False

    return render_template(
        "recap.html",
        site_title=site_name,
        title=_("Recap"),
        session=session,
        top_songs=_song_list(session) if session else [],
        songs_by_singer=_songs_by_singer_display(session) if session else {},
        live=live,
        is_latest=is_latest,
    )


@recap_bp.route("/recap/name", methods=["GET"])
@recap_bp.arguments(SetSessionNameQuery, location="query")
def set_session_name(query):
    """Set (or clear) the admin-given name for a session, identified by started_at."""
    k = get_karaoke_instance()
    if is_admin():
        k.db.set_session_name(query["started_at"], query["name"])
        return jsonify([True, _("Session name saved")])
    else:
        # MSG: Message shown after trying to name a session without admin permissions.
        flash(_("You don't have permission to name sessions"), "is-danger")
        return redirect(url_for("info.info"))


@recap_bp.route("/recap/summary")
def recap_summary():
    """JSON summary of the live session only, polled by the splash screen teaser."""
    sessions = _get_all_sessions()
    session = sessions[-1] if sessions else None
    if not session or not is_session_live(session):
        return jsonify({"active": False})

    k = get_karaoke_instance()
    top_song_path, top_song_count = session.top_songs[0]
    return jsonify(
        {
            "active": True,
            "play_count": session.play_count,
            "singer_count": session.singer_count,
            "top_song": k.song_manager.display_name_from_path(top_song_path),
            "top_song_count": top_song_count,
            "top_singer": session.top_singers[0][0] if session.top_singers else None,
        }
    )
