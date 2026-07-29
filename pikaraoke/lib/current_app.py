"""Flask application context utilities for PiKaraoke."""

import logging
import os
import subprocess
import sys
import time
from typing import Any

from flask import current_app, request
from flask_socketio import emit

from pikaraoke.karaoke import Karaoke


def is_admin() -> bool:
    """Determine if the current app's admin password matches the admin cookie value
    This function checks if the provided password is `None` or if it matches
    the value of the "admin" cookie in the current Flask request. If the password
    is `None`, the function assumes the user is an admin. If the "admin" cookie
    is present and its value matches the provided password, the function returns `True`.
    Otherwise, it returns `False`.
    Returns:
        bool: `True` if the password matches the admin cookie or if the password is `None`,
              `False` otherwise.
    """
    password = get_admin_password()
    return password is None or request.cookies.get("admin") == password


def get_karaoke_instance() -> Karaoke:
    """Get the current app's Karaoke instance
    This function returns the Karaoke instance stored in the current app's configuration.
    Returns:
        Karaoke: The Karaoke instance stored in the current app's configuration.
    """
    return current_app.config["KARAOKE_INSTANCE"]


def get_admin_password() -> str:
    """Get the admin password from the current app's configuration
    This function returns the admin password stored in the current app's configuration.
    Returns:
        str: The admin password stored in the current app's configuration.
    """
    return current_app.config["ADMIN_PASSWORD"]


def get_client_ip() -> str:
    """Get the requesting client's IP address, for the audit log and honeypot blocklist.

    Prefers CF-Connecting-IP (set by Cloudflare's edge -- the authoritative real
    visitor IP when running behind Cloudflare, including Cloudflare Tunnel, where
    it's also trustworthy: with Tunnel the origin has no exposed port, so every
    request is guaranteed to have passed through Cloudflare's edge first, which
    sets this header itself -- nothing can reach the origin directly to forge it).
    Falls back to the first hop in X-Forwarded-For (a generic reverse proxy), then
    request.remote_addr, which would otherwise just be the proxy's own IP.
    """
    cf_connecting_ip = request.headers.get("CF-Connecting-IP")
    if cf_connecting_ip:
        return cf_connecting_ip.strip()
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.remote_addr or "Unknown"


def is_action_blocked(k: Karaoke, user: str) -> bool:
    """Check whether a party-disrupting action (queue/playback) should be
    silently no-op'd instead of performed.

    Blocks on two signals, both meant to catch bots rather than real guests:
    - The requesting IP tripped the Browse page honeypot.
    - No display name was sent at all -- every real browser has one by the
      time any button is clickable, since base.html prompts for it on the
      first page load. A request with none skipped that entirely.
    """
    if k.ip_blocklist.is_blocked(get_client_ip()):
        return True
    return not user or not user.strip()


def get_site_name() -> str:
    """Get the site name from the current app's configuration
    This function returns the site name stored in the current app's configuration.
    Returns:
        str: The site name stored in the current app's configuration.
    """
    return current_app.config["SITE_NAME"]


def broadcast_event(event: str, data: Any = None) -> None:
    """Broadcast a SocketIO event to all connected clients.

    Args:
        event: Name of the event to broadcast.
        data: Optional data payload to send with the event.
    """
    logging.debug("Broadcasting event: " + event)
    emit(event, data, namespace="/", broadcast=True)


def delayed_halt(cmd: int) -> None:
    """Execute a delayed system halt command.

    Clears the queue, stops the karaoke instance, then executes the command.

    Args:
        cmd: Command to execute:
            0 = exit application
            1 = shutdown system
            2 = reboot system
            3 = expand rootfs and reboot (Raspberry Pi)
    """
    time.sleep(1.5)
    k = get_karaoke_instance()
    k.queue_manager.queue_clear()
    k.stop()
    if cmd == 0:
        sys.exit()
    if cmd == 1:
        os.system("shutdown now")
    if cmd == 2:
        os.system("reboot")
    if cmd == 3:
        process = subprocess.Popen(["raspi-config", "--expand-rootfs"])
        process.wait()
        os.system("reboot")
