"""Socket.IO event handlers for PiKaraoke."""

import logging

from flask import request
from flask_socketio import join_room

from pikaraoke.lib.current_app import get_client_ip, get_device_id, get_karaoke_instance
from pikaraoke.lib.splash_registry import SplashRegistry

# Splash screens share a room so playback position updates don't fan out to
# every guest's phone, which never listen for them.
SPLASH_ROOM = "splash"

splash_registry = SplashRegistry()

# Held so HTTP routes (the admin page changing the master) can push role
# changes to screens without importing the app and creating a cycle.
_socketio = None


def broadcast_splash_role(sid: str, role: str) -> None:
    """Tell one splash screen which role it now holds."""
    if _socketio is not None:
        _socketio.emit("splash_role", role, room=sid)


def broadcast_seek(position: float) -> None:
    """Ask every splash screen to jump to a position, in seconds.

    Sent to all of them rather than only the master so they move together.
    Waiting for the followers' drift correction would leave them up to a
    second behind, which is very visible on a wall of TVs.
    """
    if _socketio is not None:
        _socketio.emit("seek", position, room=SPLASH_ROOM)


def setup_socket_events(socketio):
    """Register Socket.IO event handlers.

    Args:
        socketio: The SocketIO instance.
    """
    global _socketio
    _socketio = socketio

    @socketio.on("end_song")
    def end_song(reason: str) -> None:
        """Handle end_song WebSocket event from the master splash screen.

        Gated server-side, not just in the client: ending a song affects
        everyone in the room, so a second screen (or a stale tab from an
        earlier session) must not be able to cut someone's song short.

        Args:
            reason: Reason for ending the song (e.g., 'complete', 'error').
        """
        sid = request.sid
        if not splash_registry.is_master(sid):
            logging.debug(f"Ignoring end_song from non-master splash: {sid}")
            return
        k = get_karaoke_instance()
        k.playback_controller.end_song(reason)

    @socketio.on("start_song")
    def start_song() -> None:
        """Handle start_song WebSocket event when playback begins.

        Accepted from any splash screen, not just the master: it's idempotent,
        and gating it meant a stale master left nobody able to report that a
        song had begun, so every song timed out and was skipped.
        """
        k = get_karaoke_instance()
        k.playback_controller.start_song()

        # A screen reporting playback is a chance to notice the master has gone
        # quiet. Only ever hands over when another screen can take the role --
        # demoting a lone screen during a blip would just leave nobody able to
        # end the song.
        promoted = splash_registry.demote_stale_master()
        if promoted:
            logging.info(f"Master splash went quiet; promoting {promoted}")
            socketio.emit("splash_role", "master", room=promoted)

    @socketio.on("clear_notification")
    def clear_notification() -> None:
        """Handle clear_notification WebSocket event to dismiss notifications."""
        k = get_karaoke_instance()
        k.reset_now_playing_notification()

    @socketio.on("register_splash")
    def register_splash() -> None:
        """Handle splash screen registration and assign master/slave roles."""
        sid = request.sid
        # Joining a room keeps position updates off every guest's phone, none
        # of which listen for them.
        join_room(SPLASH_ROOM)

        # Pull the admin's pinned device from preferences on each registration,
        # so a choice made mid-party takes effect on the next reconnect without
        # needing to be pushed into the registry separately.
        k = get_karaoke_instance()
        splash_registry.pin_device(k.preferences.get_or_default("master_splash_device"))

        role = splash_registry.register(
            sid,
            device_id=get_device_id(),
            ip_address=get_client_ip(),
        )
        logging.info(f"Splash screen registered: {sid} ({role})")
        socketio.emit("splash_role", role, room=sid)

    @socketio.on("playback_position")
    def handle_playback_position(position: float) -> None:
        """Handle playback_position WebSocket event from the master splash screen.

        Args:
            position: Current playback position in seconds.
        """
        sid = request.sid
        if not splash_registry.is_master(sid):
            return
        # Doubles as the master's liveness signal while a song is playing.
        splash_registry.touch(sid)
        k = get_karaoke_instance()
        k.playback_controller.now_playing_position = position
        # Slaves only: guests' phones don't listen for this.
        socketio.emit("playback_position", position, room=SPLASH_ROOM, include_self=False)

    @socketio.on("disconnect")
    def handle_disconnect() -> None:
        """Handle Socket.IO client disconnection and manage splash role handover."""
        sid = request.sid
        if sid not in splash_registry.connections:
            return
        logging.info(f"Splash screen disconnected: {sid}")
        new_master = splash_registry.remove(sid)
        if new_master:
            socketio.emit("splash_role", "master", room=new_master)
            logging.info(f"New master splash elected: {new_master}")

    @socketio.on("request_mic_devices")
    def handle_request_mic_devices() -> None:
        """Client requests the current mic device list from the server."""
        k = get_karaoke_instance()
        socketio.emit(
            "mic_devices_state",
            k.sound_manager.get_enriched_devices(),
            room=request.sid,
        )

    @socketio.on("request_mic_settings")
    def handle_request_mic_settings() -> None:
        """Client requests current mic global settings (latency, echo cancel)."""
        k = get_karaoke_instance()
        socketio.emit(
            "mic_settings_state",
            k.sound_manager.get_mic_settings_state(),
            room=request.sid,
        )

    @socketio.on("mic_latency_change")
    def handle_mic_latency_change(data: dict) -> None:
        """Handle mic latency change from control UI."""
        k = get_karaoke_instance()
        latency_ms = int(data.get("latency_ms", 50))
        state = k.sound_manager.set_latency_ms(latency_ms)
        socketio.emit("mic_settings_state", state)

    @socketio.on("mic_echo_cancel_change")
    def handle_mic_echo_cancel_change(data: dict) -> None:
        """Handle echo cancellation toggle from control UI."""
        k = get_karaoke_instance()
        enabled = bool(data.get("enabled", False))
        state = k.sound_manager.set_echo_cancel(enabled)
        socketio.emit("mic_settings_state", state)

    @socketio.on("mic_refresh")
    def handle_mic_refresh() -> None:
        """Re-enumerate mic and output devices server-side and broadcast updated lists."""
        k = get_karaoke_instance()
        enriched = k.sound_manager.refresh()
        socketio.emit("mic_devices_state", enriched)

    @socketio.on("mic_update")
    def handle_mic_update(data: dict) -> None:
        """Handle mic configuration change from control UI.

        Persists settings and activates/deactivates mic server-side.
        """
        k = get_karaoke_instance()
        label = data.get("label", "")
        device_id = str(data.get("deviceId", ""))
        enabled = data.get("enabled", False)
        volume = data.get("volume", 1.0)

        if label:
            settings = k.sound_manager.load_settings()
            new_state = {"enabled": enabled, "volume": volume}
            if settings.get(label) == new_state:
                return
            settings[label] = new_state
            k.sound_manager.save_settings(settings)

        # Activate or deactivate the mic stream server-side
        if enabled:
            k.sound_manager.activate(device_id, volume)
        else:
            k.sound_manager.deactivate(device_id)

        logging.info(f"Mic update: {label} enabled={enabled} volume={volume}")
        socketio.emit("mic_update", data)
