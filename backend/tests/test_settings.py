import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import settings
from app.core import media_compositor
from app.core.model_configuration import CUSTOM_PROVIDERS, PROVIDER_OPTIONS
from app.core.providers import defaults
from app.core.providers.minimax_h3 import MiniMaxH3Client
from app.core.providers.video_adapters import ADAPTERS, RUNTIME_PROVIDER_FOR_FAMILY
from app.platform.bootstrap import development_admin_login_hint


DEPLOYMENT_VARIABLES = (
    "ENVIRONMENT", "BACKEND_HOST", "BACKEND_PORT", "BACKEND_RELOAD", "FRONTEND_PORT",
    "ALLOWED_ORIGINS", "PUBLIC_BASE_URL", "MEDIA_PUBLIC_BASE_URL", "DATABASE_URL",
    "SHARE_LINK_BASE_URL",
)


def deployment(**values: str):
    """Patch the environment to exactly these deployment variables."""
    cleared = {name: "" for name in DEPLOYMENT_VARIABLES}
    return patch.dict(os.environ, {**cleared, **values}, clear=False)


class DeploymentSettingsTests(unittest.TestCase):
    def test_unconfigured_server_keeps_the_local_development_addresses(self):
        with deployment():
            self.assertEqual(settings.server_host(), "0.0.0.0")
            self.assertEqual(settings.server_port(), 8000)
            self.assertTrue(settings.server_reload())
            self.assertEqual(
                settings.allowed_origins(),
                ["http://localhost:5173", "http://127.0.0.1:5173"],
            )
            self.assertEqual(settings.public_base_url(), "http://localhost:8000")
            self.assertEqual(settings.media_public_base_url(), "http://localhost:8000/media")
            self.assertEqual(settings.database_url(), settings.DEFAULT_DATABASE_URL)
            self.assertEqual(
                settings.share_link_url("general_revenge_king"),
                "https://short-drama.volces.com/s/general_revenge_king",
            )

    def test_moving_a_port_moves_everything_derived_from_it(self):
        with deployment(BACKEND_PORT="9100", FRONTEND_PORT="5200"):
            self.assertEqual(settings.server_port(), 9100)
            self.assertEqual(settings.media_public_base_url(), "http://localhost:9100/media")
            self.assertEqual(
                settings.allowed_origins(),
                ["http://localhost:5200", "http://127.0.0.1:5200"],
            )

    def test_explicit_addresses_win_over_derived_ones(self):
        with deployment(
            BACKEND_PORT="9100",
            PUBLIC_BASE_URL="https://drama.example.com/",
            ALLOWED_ORIGINS=" https://drama.example.com , https://admin.example.com ,",
            DATABASE_URL="postgresql+asyncpg://app@db.internal/drama",
            SHARE_LINK_BASE_URL="https://s.example.com/",
        ):
            self.assertEqual(settings.media_public_base_url(), "https://drama.example.com/media")
            self.assertEqual(
                settings.allowed_origins(),
                ["https://drama.example.com", "https://admin.example.com"],
            )
            self.assertEqual(settings.database_url(), "postgresql+asyncpg://app@db.internal/drama")
            self.assertEqual(settings.share_link_url("abc"), "https://s.example.com/abc")
        with deployment(
            PUBLIC_BASE_URL="https://drama.example.com",
            MEDIA_PUBLIC_BASE_URL="https://cdn.example.com/media",
        ):
            self.assertEqual(settings.media_public_base_url(), "https://cdn.example.com/media")

    def test_a_port_that_is_not_a_port_is_reported_by_name(self):
        for value in ("eight-thousand", "0", "70000"):
            with deployment(BACKEND_PORT=value), self.assertRaisesRegex(RuntimeError, "BACKEND_PORT"):
                settings.server_port()

    def test_production_is_recognised_and_stops_auto_reload_by_default(self):
        for name in ("production", "PROD", " Production "):
            with deployment(ENVIRONMENT=name):
                self.assertTrue(settings.is_production())
                self.assertFalse(settings.server_reload())
        with deployment(ENVIRONMENT="staging"):
            self.assertFalse(settings.is_production())
        with deployment(ENVIRONMENT="production", BACKEND_RELOAD="1"):
            self.assertTrue(settings.server_reload())
        with deployment(BACKEND_RELOAD="off"):
            self.assertFalse(settings.server_reload())


class DevelopmentAdminHintTests(unittest.TestCase):
    def test_login_page_hint_names_the_configured_administrator_in_development_only(self):
        with deployment(), patch.dict(os.environ, {"BOOTSTRAP_ADMIN": "", "BOOTSTRAP_ADMIN_LOGIN": ""}):
            os.environ.pop("BOOTSTRAP_ADMIN")
            self.assertEqual(development_admin_login_hint(), "admin@short-drama")
        with deployment(), patch.dict(os.environ, {"BOOTSTRAP_ADMIN": "1", "BOOTSTRAP_ADMIN_LOGIN": " Owner@Studio.test "}):
            self.assertEqual(development_admin_login_hint(), "owner@studio.test")
        with deployment(), patch.dict(os.environ, {"BOOTSTRAP_ADMIN": "0"}):
            self.assertIsNone(development_admin_login_hint())
        with deployment(ENVIRONMENT="production"), patch.dict(os.environ, {"BOOTSTRAP_ADMIN": "1"}):
            self.assertIsNone(development_admin_login_hint())


class OwnMediaResolutionTests(unittest.TestCase):
    def test_media_on_the_configured_public_host_is_read_from_disk(self):
        with tempfile.TemporaryDirectory() as media_dir:
            clip = Path(media_dir) / "film.mp4"
            clip.write_bytes(b"x")
            expected = os.path.realpath(clip)
            with (
                patch.object(media_compositor, "MEDIA_DIR", media_dir),
                patch.object(media_compositor, "PUBLIC_BASE_URL", "https://drama.example.com/media"),
            ):
                resolve = media_compositor._local_media_source
                self.assertEqual(resolve("https://drama.example.com/media/film.mp4"), expected)
                self.assertEqual(resolve("http://localhost:8000/media/film.mp4"), expected)
                self.assertEqual(resolve("/media/film.mp4"), expected)
                self.assertIsNone(resolve("https://elsewhere.example.com/media/film.mp4"))
                self.assertIsNone(resolve("https://drama.example.com/media/../secret.txt"))


class ProviderDefaultTests(unittest.TestCase):
    def test_configuration_center_offers_the_shared_default_addresses(self):
        for options in PROVIDER_OPTIONS.values():
            for option in options:
                if option["id"] in CUSTOM_PROVIDERS:
                    # A provider the person brings has no default address of its own.
                    self.assertEqual(option["default_base_url"], "")
                    continue
                self.assertEqual(
                    option["default_base_url"],
                    defaults.PROVIDER_DEFAULT_BASE_URLS[option["id"]],
                )

    def test_video_adapters_and_configuration_center_agree_on_every_address(self):
        for family, adapter in ADAPTERS.items():
            provider = RUNTIME_PROVIDER_FOR_FAMILY[family]
            self.assertEqual(adapter.default_base_url, defaults.PROVIDER_DEFAULT_BASE_URLS[provider])

    def test_gateway_reaches_seedance_through_ark_by_default(self):
        self.assertEqual(defaults.GATEWAY_DEFAULT_BASE_URLS["seedance"], defaults.ARK_BASE_URL)

    def test_h3_follows_the_configured_minimax_host(self):
        base = {"MINIMAX_H3_ENDPOINT": "", "MINIMAX_H3_STATUS_URL_TEMPLATE": "", "MINIMAX_FILES_URL": ""}
        with patch.dict(os.environ, {**base, "MINIMAX_BASE_URL": ""}, clear=False):
            client = MiniMaxH3Client(api_key="k")
            self.addCleanup(client.close)
            self.assertEqual(client.endpoint, "https://api.minimaxi.com/v2/video_generation")
        with patch.dict(os.environ, {**base, "MINIMAX_BASE_URL": "https://api.minimax.io/v1/t2a_v2"}, clear=False):
            client = MiniMaxH3Client(api_key="k")
            self.addCleanup(client.close)
            self.assertEqual(client.endpoint, "https://api.minimax.io/v2/video_generation")
            self.assertEqual(client.files_url, "https://api.minimax.io/v1/files/retrieve")
        with patch.dict(
            os.environ,
            {**base, "MINIMAX_BASE_URL": "https://api.minimax.io", "MINIMAX_H3_ENDPOINT": "https://h3.example.com/v2/video_generation"},
            clear=False,
        ):
            client = MiniMaxH3Client(api_key="k")
            self.addCleanup(client.close)
            self.assertEqual(client.endpoint, "https://h3.example.com/v2/video_generation")


class NoHardcodedDeploymentValuesTests(unittest.TestCase):
    """Addresses of this deployment live in app/settings.py and nowhere else."""

    def test_backend_sources_name_no_local_address_or_developer_path(self):
        backend_root = Path(settings.__file__).resolve().parents[1]
        sources = [backend_root / "main.py", *sorted((backend_root / "app").rglob("*.py"))]
        allowed = {Path(settings.__file__).resolve()}
        offenders = []
        for source in sources:
            if source.resolve() in allowed:
                continue
            text = source.read_text(encoding="utf-8")
            for needle in ("://localhost", "://127.0.0.1:8000", "://127.0.0.1:5173", "/Users/"):
                if needle in text:
                    offenders.append(f"{source.relative_to(backend_root)}: {needle}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
