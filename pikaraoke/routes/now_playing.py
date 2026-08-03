"""Now playing status endpoint."""

import json
import logging

from flask_smorest import Blueprint

from pikaraoke.lib.current_app import get_device_id, get_karaoke_instance

nowplaying_bp = Blueprint("now_playing", __name__)


@nowplaying_bp.route("/now_playing")
def now_playing():
    """Get current playback status.

    Adds a per-requester ownership flag. It's computed here rather than in
    Karaoke.get_now_playing() because that state is also broadcast over
    SocketIO to every client at once, where "mine" has no meaning -- and
    because the device token itself must never be sent to the browser.
    """
    k = get_karaoke_instance()
    try:
        state = k.get_now_playing()
        device_id = get_device_id()
        state["now_playing_is_mine"] = bool(device_id) and (
            device_id == k.playback_controller.now_playing_device
        )
        return json.dumps(state)
    except Exception as e:
        logging.error("Problem loading /nowplaying, pikaraoke may still be starting up: " + str(e))
        return ""
