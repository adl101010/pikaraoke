"""Playback control routes for skip, pause, volume, and transpose."""

import flask_babel
from flask import flash, redirect, request, url_for
from flask_smorest import Blueprint

from pikaraoke.lib.current_app import broadcast_event, get_karaoke_instance, is_admin

_ = flask_babel.gettext


controller_bp = Blueprint("controller", __name__)


@controller_bp.route("/skip")
def skip():
    """Skip the currently playing song."""
    if not is_admin():
        # MSG: Message shown after trying to skip a song without admin permissions.
        flash(_("You don't have permission to skip songs"), "is-danger")
        return redirect(url_for("home.home"))
    k = get_karaoke_instance()
    k.audit_log.record(
        request.args.get("user", ""), _("Skipped song"), k.playback_controller.now_playing or ""
    )
    broadcast_event("skip", "user command")
    k.playback_controller.skip()
    return redirect(url_for("home.home"))


@controller_bp.route("/pause")
def pause():
    """Toggle pause/resume playback."""
    k = get_karaoke_instance()
    if k.playback_controller.is_paused:
        action = _("Resumed playback")
        broadcast_event("play")
    else:
        action = _("Paused playback")
        broadcast_event("pause")
    k.audit_log.record(request.args.get("user", ""), action, k.playback_controller.now_playing or "")
    k.playback_controller.pause()
    return redirect(url_for("home.home"))


@controller_bp.route("/transpose/<semitones>", methods=["GET"])
def transpose(semitones):
    """Transpose (pitch shift) the current song."""
    k = get_karaoke_instance()
    k.audit_log.record(
        request.args.get("user", ""),
        _("Changed key"),
        "%s semitones -- %s" % (semitones, k.playback_controller.now_playing or ""),
    )
    broadcast_event("skip", "transpose current")
    k.transpose_current(int(semitones))
    return redirect(url_for("home.home"))


@controller_bp.route("/restart")
def restart():
    """Restart the current song from the beginning."""
    k = get_karaoke_instance()
    broadcast_event("restart")
    k.restart()
    return redirect(url_for("home.home"))


@controller_bp.route("/volume/<volume>")
def volume(volume):
    """Set the playback volume."""
    k = get_karaoke_instance()
    k.audit_log.record(request.args.get("user", ""), _("Changed volume"), str(volume))
    broadcast_event("volume", volume)
    k.volume_change(float(volume))
    return redirect(url_for("home.home"))


@controller_bp.route("/vol_up")
def vol_up():
    """Increase volume by 10%."""
    k = get_karaoke_instance()
    k.audit_log.record(request.args.get("user", ""), _("Increased volume"))
    broadcast_event("volume", "up")
    k.vol_up()
    return redirect(url_for("home.home"))


@controller_bp.route("/vol_down")
def vol_down():
    """Decrease volume by 10%."""
    k = get_karaoke_instance()
    k.audit_log.record(request.args.get("user", ""), _("Decreased volume"))
    broadcast_event("volume", "down")
    k.vol_down()
    return redirect(url_for("home.home"))
