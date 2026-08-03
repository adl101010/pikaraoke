"""Playback control routes for skip, pause, volume, and transpose."""

import flask_babel
from flask import flash, redirect, request, url_for
from flask_smorest import Blueprint

from pikaraoke.lib.current_app import (
    broadcast_event,
    get_client_ip,
    get_device_id,
    get_karaoke_instance,
    is_action_blocked,
    is_admin,
)

_ = flask_babel.gettext


controller_bp = Blueprint("controller", __name__)


@controller_bp.route("/skip")
def skip():
    """Skip the currently playing song.

    Admins can skip anyone's song; everyone else can only skip their own.
    Ownership is keyed on the device that queued the song, not the display
    name -- renaming yourself to match the current singer grants nothing.
    """
    k = get_karaoke_instance()
    user = request.args.get("user", "")
    device_id = get_device_id()
    admin = is_admin()

    if not admin:
        if is_action_blocked(k, user):
            return redirect(url_for("home.home"))
        if not device_id or device_id != k.playback_controller.now_playing_device:
            # MSG: Message shown after trying to skip someone else's song without admin permissions.
            flash(_("You can only skip your own songs"), "is-danger")
            return redirect(url_for("home.home"))

    k.audit_log.record(
        user,
        # MSG: Audit log entry when an admin skips a song.
        _("Skipped song") if admin else _("Skipped own song"),
        k.playback_controller.now_playing or "",
        get_client_ip(),
        device_id,
    )
    broadcast_event("skip", "user command")
    k.playback_controller.skip()
    return redirect(url_for("home.home"))


@controller_bp.route("/pause")
def pause():
    """Toggle pause/resume playback."""
    k = get_karaoke_instance()
    user = request.args.get("user", "")
    if is_action_blocked(k, user):
        return redirect(url_for("home.home"))
    if k.playback_controller.is_paused:
        action = _("Resumed playback")
        broadcast_event("play")
    else:
        action = _("Paused playback")
        broadcast_event("pause")
    k.audit_log.record(user, action, k.playback_controller.now_playing or "", get_client_ip())
    k.playback_controller.pause()
    return redirect(url_for("home.home"))


@controller_bp.route("/transpose/<semitones>", methods=["GET"])
def transpose(semitones):
    """Transpose (pitch shift) the current song."""
    k = get_karaoke_instance()
    user = request.args.get("user", "")
    if is_action_blocked(k, user):
        return redirect(url_for("home.home"))
    k.audit_log.record(
        user,
        _("Changed key"),
        "%s semitones -- %s" % (semitones, k.playback_controller.now_playing or ""),
        get_client_ip(),
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
    user = request.args.get("user", "")
    if is_action_blocked(k, user):
        return redirect(url_for("home.home"))
    k.audit_log.record(user, _("Changed volume"), str(volume), get_client_ip())
    broadcast_event("volume", volume)
    k.volume_change(float(volume))
    return redirect(url_for("home.home"))


@controller_bp.route("/vol_up")
def vol_up():
    """Increase volume by 10%."""
    k = get_karaoke_instance()
    user = request.args.get("user", "")
    if is_action_blocked(k, user):
        return redirect(url_for("home.home"))
    k.audit_log.record(user, _("Increased volume"), "", get_client_ip())
    broadcast_event("volume", "up")
    k.vol_up()
    return redirect(url_for("home.home"))


@controller_bp.route("/vol_down")
def vol_down():
    """Decrease volume by 10%."""
    k = get_karaoke_instance()
    user = request.args.get("user", "")
    if is_action_blocked(k, user):
        return redirect(url_for("home.home"))
    k.audit_log.record(user, _("Decreased volume"), "", get_client_ip())
    broadcast_event("volume", "down")
    k.vol_down()
    return redirect(url_for("home.home"))
