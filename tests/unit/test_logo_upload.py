"""Tests for the admin-only custom logo upload/reset routes."""

import io
import os
from unittest.mock import MagicMock, patch

import pytest
import werkzeug
from flask import Flask

if not hasattr(werkzeug, "__version__"):
    werkzeug.__version__ = "3.0.0"

from pikaraoke.routes.images import PNG_MAGIC_BYTES, images_bp
from pikaraoke.routes.info import info_bp

# A minimal but valid 1x1 PNG.
VALID_PNG = (
    PNG_MAGIC_BYTES
    + bytes.fromhex(
        "0000000d4948445200000001000000010802000000907753"
        "de0000000c4944415478da6360606060000000050001a5f645400000000049454e44ae426082"
    )
)


@pytest.fixture
def app():
    app = Flask(__name__)
    app.secret_key = "test"
    app.register_blueprint(images_bp)
    app.register_blueprint(info_bp)
    app.extensions["babel"] = MagicMock()
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def fake_custom_logo_path(tmp_path):
    return str(tmp_path / "custom_logo.png")


class TestUploadLogo:
    @patch("pikaraoke.routes.images.is_admin", return_value=False)
    @patch("pikaraoke.routes.images._", side_effect=lambda x: x)
    def test_non_admin_upload_is_blocked(self, mock_gettext, mock_is_admin, client, fake_custom_logo_path):
        response = client.post(
            "/logo/upload",
            data={"logo": (io.BytesIO(VALID_PNG), "logo.png")},
            content_type="multipart/form-data",
        )
        assert response.status_code == 302
        assert not os.path.isfile(fake_custom_logo_path)

    @patch("pikaraoke.routes.images.is_admin", return_value=True)
    @patch("pikaraoke.routes.images.get_custom_logo_path")
    @patch("pikaraoke.routes.images.get_karaoke_instance")
    @patch("pikaraoke.routes.images._", side_effect=lambda x: x)
    def test_admin_upload_saves_file_and_updates_logo_path(
        self, mock_gettext, mock_get_instance, mock_get_path, mock_is_admin, client, fake_custom_logo_path
    ):
        mock_get_path.return_value = fake_custom_logo_path
        mock_karaoke = MagicMock()
        mock_get_instance.return_value = mock_karaoke

        response = client.post(
            "/logo/upload",
            data={"logo": (io.BytesIO(VALID_PNG), "logo.png")},
            content_type="multipart/form-data",
        )

        assert response.status_code == 302
        assert os.path.isfile(fake_custom_logo_path)
        with open(fake_custom_logo_path, "rb") as f:
            assert f.read() == VALID_PNG
        assert mock_karaoke.logo_path == fake_custom_logo_path

    @patch("pikaraoke.routes.images.is_admin", return_value=True)
    @patch("pikaraoke.routes.images.get_custom_logo_path")
    @patch("pikaraoke.routes.images.get_karaoke_instance")
    @patch("pikaraoke.routes.images._", side_effect=lambda x: x)
    def test_rejects_non_png_content(
        self, mock_gettext, mock_get_instance, mock_get_path, mock_is_admin, client, fake_custom_logo_path
    ):
        mock_get_path.return_value = fake_custom_logo_path
        mock_get_instance.return_value = MagicMock()

        response = client.post(
            "/logo/upload",
            data={"logo": (io.BytesIO(b"not a real png"), "logo.png")},
            content_type="multipart/form-data",
        )

        assert response.status_code == 302
        assert not os.path.isfile(fake_custom_logo_path)

    @patch("pikaraoke.routes.images.is_admin", return_value=True)
    @patch("pikaraoke.routes.images.get_custom_logo_path")
    @patch("pikaraoke.routes.images.get_karaoke_instance")
    @patch("pikaraoke.routes.images._", side_effect=lambda x: x)
    def test_rejects_oversized_file(
        self, mock_gettext, mock_get_instance, mock_get_path, mock_is_admin, client, fake_custom_logo_path
    ):
        mock_get_path.return_value = fake_custom_logo_path
        mock_get_instance.return_value = MagicMock()

        oversized = PNG_MAGIC_BYTES + b"\x00" * (5 * 1024 * 1024 + 1)
        response = client.post(
            "/logo/upload",
            data={"logo": (io.BytesIO(oversized), "logo.png")},
            content_type="multipart/form-data",
        )

        assert response.status_code == 302
        assert not os.path.isfile(fake_custom_logo_path)

    @patch("pikaraoke.routes.images.is_admin", return_value=True)
    @patch("pikaraoke.routes.images._", side_effect=lambda x: x)
    def test_rejects_missing_file(self, mock_gettext, mock_is_admin, client):
        response = client.post("/logo/upload", data={}, content_type="multipart/form-data")
        assert response.status_code == 302


class TestResetLogo:
    @patch("pikaraoke.routes.images.is_admin", return_value=False)
    @patch("pikaraoke.routes.images._", side_effect=lambda x: x)
    def test_non_admin_reset_is_blocked(self, mock_gettext, mock_is_admin, client):
        response = client.get("/logo/reset")
        assert response.status_code == 302

    @patch("pikaraoke.routes.images.is_admin", return_value=True)
    @patch("pikaraoke.routes.images.get_custom_logo_path")
    @patch("pikaraoke.routes.images.get_karaoke_instance")
    @patch("pikaraoke.routes.images._", side_effect=lambda x: x)
    def test_admin_reset_removes_file_and_restores_default(
        self, mock_gettext, mock_get_instance, mock_get_path, mock_is_admin, client, fake_custom_logo_path
    ):
        mock_get_path.return_value = fake_custom_logo_path
        with open(fake_custom_logo_path, "wb") as f:
            f.write(VALID_PNG)

        mock_karaoke = MagicMock()
        mock_karaoke.default_logo_path = "/default/logo.png"
        mock_get_instance.return_value = mock_karaoke

        response = client.get("/logo/reset")

        assert response.status_code == 302
        assert not os.path.isfile(fake_custom_logo_path)
        assert mock_karaoke.logo_path == "/default/logo.png"

    @patch("pikaraoke.routes.images.is_admin", return_value=True)
    @patch("pikaraoke.routes.images.get_custom_logo_path")
    @patch("pikaraoke.routes.images.get_karaoke_instance")
    @patch("pikaraoke.routes.images._", side_effect=lambda x: x)
    def test_reset_when_no_custom_logo_exists(
        self, mock_gettext, mock_get_instance, mock_get_path, mock_is_admin, client, fake_custom_logo_path
    ):
        mock_get_path.return_value = fake_custom_logo_path
        mock_karaoke = MagicMock()
        mock_karaoke.default_logo_path = "/default/logo.png"
        mock_get_instance.return_value = mock_karaoke

        response = client.get("/logo/reset")

        assert response.status_code == 302
        assert mock_karaoke.logo_path == "/default/logo.png"
