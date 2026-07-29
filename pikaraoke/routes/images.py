"""Image serving routes for QR code and logo."""
import os

import flask_babel
from flask import flash, redirect, request, send_file, url_for
from flask_smorest import Blueprint

from pikaraoke.lib.current_app import get_karaoke_instance, is_admin
from pikaraoke.lib.get_platform import get_custom_logo_path

_ = flask_babel.gettext

images_bp = Blueprint("images", __name__)

MAX_LOGO_SIZE_BYTES = 5 * 1024 * 1024  # 5MB
PNG_MAGIC_BYTES = b"\x89PNG\r\n\x1a\n"


@images_bp.route("/qrcode")
def qrcode():
    """Get QR code image for the web interface URL."""
    k = get_karaoke_instance()
    return send_file(k.qr_code_path, mimetype="image/png")


@images_bp.route("/logo")
def logo():
    """Get the PiKaraoke logo image."""
    k = get_karaoke_instance()
    return send_file(os.path.abspath(k.logo_path), mimetype="image/png")


@images_bp.route("/logo/upload", methods=["POST"])
def upload_logo():
    """Upload a custom logo image to replace the default (admin only). PNG only."""
    if not is_admin():
        # MSG: Message shown after trying to upload a logo without admin permissions.
        flash(_("You don't have permission to change the logo"), "is-danger")
        return redirect(url_for("info.info"))

    uploaded = request.files.get("logo")
    if not uploaded or not uploaded.filename:
        # MSG: Message shown after submitting the logo upload form with no file selected.
        flash(_("No file was selected"), "is-danger")
        return redirect(url_for("info.info"))

    data = uploaded.read(MAX_LOGO_SIZE_BYTES + 1)
    if len(data) > MAX_LOGO_SIZE_BYTES:
        # MSG: Message shown after uploading a logo file that's too large.
        flash(_("Logo file is too large (max 5MB)"), "is-danger")
        return redirect(url_for("info.info"))

    if not data.startswith(PNG_MAGIC_BYTES):
        # MSG: Message shown after uploading a logo file that isn't a valid PNG.
        flash(_("Logo must be a PNG image"), "is-danger")
        return redirect(url_for("info.info"))

    custom_logo_path = get_custom_logo_path()
    with open(custom_logo_path, "wb") as f:
        f.write(data)

    k = get_karaoke_instance()
    k.logo_path = custom_logo_path
    # MSG: Message shown after successfully uploading a new logo.
    flash(_("Logo updated!"), "is-success")
    return redirect(url_for("info.info"))


@images_bp.route("/logo/reset")
def reset_logo():
    """Reset the logo back to the PiKaraoke default (admin only)."""
    if not is_admin():
        # MSG: Message shown after trying to reset the logo without admin permissions.
        flash(_("You don't have permission to change the logo"), "is-danger")
        return redirect(url_for("info.info"))

    k = get_karaoke_instance()
    custom_logo_path = get_custom_logo_path()
    if os.path.isfile(custom_logo_path):
        os.remove(custom_logo_path)
    k.logo_path = k.default_logo_path
    # MSG: Message shown after resetting the logo to the default.
    flash(_("Logo reset to default"), "is-success")
    return redirect(url_for("info.info"))
