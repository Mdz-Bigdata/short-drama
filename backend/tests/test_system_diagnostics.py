import asyncio
import io
import json
import logging
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import platform_api
from app.api.auth_api import get_current_user
from app.core import system_diagnostics as diagnostics
from app.platform.dependencies import get_platform_store


class RedactTest(unittest.TestCase):
    def test_keys_tokens_and_named_secrets_are_masked(self):
        said = diagnostics.redact(
            'Authorization: Bearer abc.def-123456 api_key="sk-live-9f8e7d6c5b4a" ARK_API_KEY=3f2a9c password: hunter22 next=1'
        )
        for secret in ("abc.def-123456", "sk-live-9f8e7d6c5b4a", "3f2a9c", "hunter22"):
            self.assertNotIn(secret, said)
        self.assertIn("next=1", said)

    def test_an_address_keeps_its_host_and_path_but_not_its_credentials_or_query(self):
        said = diagnostics.redact(
            "postgresql+asyncpg://admin:s3cret@db.internal:5432/short-drama and "
            "https://cdn.example.com/clip/7.mp4?X-Signature=deadbeef&Expires=99"
        )
        self.assertIn("db.internal:5432/short-drama", said)
        self.assertIn("https://cdn.example.com/clip/7.mp4?***", said)
        for secret in ("admin", "s3cret", "deadbeef", "Expires"):
            self.assertNotIn(secret, said)

    def test_personal_details_and_opaque_strings_are_masked_and_ids_stay(self):
        task = "0bdf86e6-6e01-4f88-96a5-71102ef34bf9"
        said = diagnostics.redact(
            f"user a.b+c@mail.example.com phone 13812345678 task {task} blob {'Zx9' * 14} stage 4 took 58123 ms"
        )
        self.assertNotIn("mail.example.com", said)
        self.assertNotIn("13812345678", said)
        self.assertNotIn("Zx9Zx9", said)
        self.assertIn(task, said)
        self.assertIn("58123 ms", said)

    def test_the_home_directory_is_written_as_a_tilde_and_the_rest_of_a_path_stays(self):
        home = str(Path.home())
        deep = "/myProduct/short-drama/backend/generated_media/final"
        self.assertEqual(diagnostics.redact(f"{home}{deep}"), f"~{deep}")
        self.assertEqual(diagnostics.redact(f"/opt/homebrew/Cellar/ffmpeg/7.1.1_3/bin/ffmpeg"), "/opt/homebrew/Cellar/ffmpeg/7.1.1_3/bin/ffmpeg")

    def test_padded_base64_is_masked_even_with_slashes(self):
        blob = "QUJD/REVG+R0hJ/SktM" * 3 + "=="
        self.assertNotIn("REVG", diagnostics.redact(f"body {blob} end"))


class SettingsReportTest(unittest.TestCase):
    def test_only_numbers_and_switches_show_their_value(self):
        report = diagnostics.settings_report(
            ["WIDTH", "FLAG", "KEY", "URL", "MODE", "MISSING"],
            {"WIDTH": "6", "FLAG": "off", "KEY": "sk-abcdef", "URL": "https://x.example/y", "MODE": "aside"},
        )
        self.assertEqual(report["WIDTH"], {"set": True, "value": "6"})
        self.assertEqual(report["FLAG"], {"set": True, "value": "off"})
        self.assertFalse(report["MISSING"]["set"])
        for name, secret in (("KEY", "sk-abcdef"), ("URL", "x.example"), ("MODE", "aside")):
            self.assertTrue(report[name]["set"])
            self.assertNotIn(secret, report[name]["value"])
        self.assertIn("9", report["KEY"]["value"])

    def test_names_come_from_every_assignment_line_commented_or_not(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / ".env.example"
            file.write_text("# a note about keys\nARK_API_KEY=YOUR_KEY\n# STAGE3_WIDTH=4\nlower=1\n\n", encoding="utf-8")
            names = diagnostics.known_setting_names(file, Path(folder) / "absent")
        self.assertEqual(names, ["ARK_API_KEY", "STAGE3_WIDTH"])


class ChecksTest(unittest.TestCase):
    def _by_id(self, findings):
        return {item.id: item for item in findings}

    def test_a_healthy_machine_passes_the_local_checks(self):
        found = self._by_id(diagnostics.local_checks(lambda: 7))
        self.assertEqual(found["runtime"].status, "ok")
        self.assertEqual(found["task_store"].status, "ok")
        self.assertIn("7", found["task_store"].detail)
        self.assertEqual(found["skills"].status, "ok")
        self.assertNotIn(str(Path.home()), " ".join(item.detail for item in found.values()))
        self.assertIn("generated_media", found["media_dir"].detail)

    def test_a_missing_folder_low_disk_and_a_dead_store_are_reported_not_raised(self):
        usage = mock.Mock(free=200 * 1024 ** 2, total=500 * 1024 ** 3)

        def dead() -> int:
            raise RuntimeError("connection refused for postgres://u:pw@db/x")

        with mock.patch.object(diagnostics, "_media_dir", return_value=Path("/nonexistent/diagnostics-test")), \
                mock.patch.object(diagnostics.shutil, "disk_usage", return_value=usage):
            found = self._by_id(diagnostics.local_checks(dead))
        self.assertEqual(found["media_dir"].status, "error")
        self.assertEqual(found["disk"].status, "error")
        self.assertIn("200", found["disk"].detail)
        self.assertEqual(found["task_store"].status, "error")
        self.assertNotIn("pw", found["task_store"].detail)

    def test_disk_between_the_two_limits_is_a_warning(self):
        usage = mock.Mock(free=3 * 1024 ** 3, total=500 * 1024 ** 3)
        with mock.patch.object(diagnostics.shutil, "disk_usage", return_value=usage):
            found = self._by_id(diagnostics.local_checks())
        self.assertEqual(found["disk"].status, "warning")
        self.assertNotIn("task_store", found)

    def test_missing_binaries_and_models_are_named(self):
        from app.core import media_compositor
        from app.platform import runtime_models

        with mock.patch.object(media_compositor, "_ffmpeg", return_value=None), \
                mock.patch.object(media_compositor, "_ffprobe", return_value=None), \
                mock.patch.object(runtime_models.runtime_model_registry, "list", return_value=()):
            found = self._by_id(diagnostics.local_checks())
        self.assertEqual(found["ffmpeg"].status, "error")
        self.assertEqual(found["ffprobe"].status, "warning")
        self.assertEqual(found["models"].status, "warning")
        for kind in ("文本", "图片", "视频"):
            self.assertIn(kind, found["models"].detail)

    def test_a_check_that_breaks_does_not_hide_the_others(self):
        with mock.patch.object(diagnostics, "_check_skills", side_effect=ValueError("boom")):
            found = self._by_id(diagnostics.local_checks())
        self.assertEqual(found["skills"].status, "error")
        self.assertIn("boom", found["skills"].detail)
        self.assertEqual(found["runtime"].status, "ok")

    def test_run_places_the_platform_store_and_reports_the_worst_status(self):
        async def dead() -> int:
            raise ConnectionError("no route")

        async def alive() -> int:
            return 3

        report = asyncio.run(diagnostics.run(dead, lambda: 1))
        ids = [item["id"] for item in report["checks"]]
        self.assertEqual(ids.index("platform_store"), ids.index("task_store") + 1)
        self.assertEqual(report["status"], "error")
        self.assertEqual(report["counts"]["error"], sum(1 for item in report["checks"] if item["status"] == "error"))
        good = asyncio.run(diagnostics.run(alive, lambda: 1))
        self.assertEqual({item["id"]: item for item in good["checks"]}["platform_store"]["status"], "ok")


class StartupAndBundleTest(unittest.TestCase):
    def setUp(self):
        self._startup = diagnostics._startup
        self.addCleanup(lambda: setattr(diagnostics, "_startup", self._startup))

    def test_start_up_keeps_the_report_and_logs_what_is_not_well(self):
        async def dead() -> int:
            raise ConnectionError("no route")

        with self.assertLogs("app.core.system_diagnostics", level="WARNING") as logs:
            report = asyncio.run(diagnostics.startup_self_check(dead, lambda: 1))
        self.assertIs(diagnostics.startup_report(), report)
        self.assertTrue(any("账号与平台库" in line for line in logs.output))

    def test_start_up_never_raises(self):
        with mock.patch.object(diagnostics, "run", side_effect=RuntimeError("broken")), \
                self.assertLogs("app.core.system_diagnostics", level="ERROR"):
            self.assertEqual(asyncio.run(diagnostics.startup_self_check()), {})

    def test_the_bundle_holds_the_report_settings_and_a_masked_log(self):
        buffer = diagnostics.RecentLog(50)
        record = logging.LogRecord("app.x", logging.WARNING, __file__, 1, "calling %s", ("https://api.example.com/v1?key=topsecret",), None)
        buffer.emit(record)
        report = diagnostics.summarise(diagnostics.local_checks())
        with tempfile.TemporaryDirectory() as folder:
            env = Path(folder) / ".env"
            env.write_text("ARK_API_KEY=real-key-value\nWIDTH=6\n", encoding="utf-8")
            with mock.patch.object(diagnostics, "_recent", buffer), \
                    mock.patch.object(diagnostics, "_env_files", return_value=(env,)), \
                    mock.patch.dict(os.environ, {"ARK_API_KEY": "real-key-value", "WIDTH": "6"}):
                packed = diagnostics.bundle(report, version="1.0.0")
        with zipfile.ZipFile(io.BytesIO(packed)) as archive:
            self.assertEqual(sorted(archive.namelist()), ["README.txt", "recent_log.txt", "report.json", "settings.json"])
            body = json.loads(archive.read("report.json"))
            shown = json.loads(archive.read("settings.json"))
            log = archive.read("recent_log.txt").decode("utf-8")
            everything = b"".join(archive.read(name) for name in archive.namelist()).decode("utf-8")
        self.assertEqual(body["now"]["status"], report["status"])
        self.assertEqual(body["version"], "1.0.0")
        self.assertEqual(shown["WIDTH"]["value"], "6")
        self.assertIn("https://api.example.com/v1?***", log)
        for secret in ("real-key-value", "topsecret", str(Path.home())):
            self.assertNotIn(secret, everything)

    def test_the_log_buffer_keeps_only_the_latest_lines(self):
        buffer = diagnostics.RecentLog(2)
        for number in range(4):
            buffer.emit(logging.LogRecord("app.x", logging.INFO, __file__, 1, "line %s", (number,), None))
        self.assertEqual([line.rsplit(" ", 1)[-1] for line in buffer.lines()], ["2", "3"])


class StoreCountsTest(unittest.TestCase):
    def test_both_stores_count_what_they_hold(self):
        from app.platform.store import PlatformStore
        from app.repository.task_repo import TaskRepository

        with tempfile.TemporaryDirectory() as folder:
            repo = TaskRepository(str(Path(folder) / "tasks.json"))
            self.assertEqual(repo.count_tasks(), 0)
            repo.save_task("t1", {"task_id": "t1"})
            self.assertEqual(repo.count_tasks(), 1)
            repo.engine.dispose()

            async def platform() -> tuple[int, int]:
                store = PlatformStore(f"sqlite+aiosqlite:///{Path(folder) / 'platform.sqlite3'}")
                await store.create_schema()
                before = await store.count_users()
                await store.create_user(email="counted@example.com", phone=None, password="user-password-strong")
                after = await store.count_users()
                await store.close()
                return before, after

            before, after = asyncio.run(platform())
        self.assertEqual(after, before + 1)


class DiagnosticsApiTest(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(platform_api.router)
        store = mock.Mock()
        store.count_users = mock.AsyncMock(return_value=2)
        self.app.dependency_overrides[get_platform_store] = lambda: store
        patch = mock.patch.object(platform_api, "_tasks", mock.Mock(count_tasks=lambda: 5))
        patch.start()
        self.addCleanup(patch.stop)
        self.client = TestClient(self.app)

    def _sign_in(self, *permissions: str):
        self.app.dependency_overrides[get_current_user] = lambda: {
            "user_id": "u1", "username": "u1", "role": "member", "permissions": list(permissions),
        }

    def test_the_report_needs_the_platform_permission(self):
        self.assertEqual(self.client.get("/api/platform/diagnostics").status_code, 401)
        self._sign_in()
        self.assertEqual(self.client.get("/api/platform/diagnostics").status_code, 403)
        self.assertEqual(self.client.get("/api/platform/diagnostics/bundle").status_code, 403)

    def test_an_administrator_reads_the_report_and_downloads_the_bundle(self):
        self._sign_in("capability:manage")
        answer = self.client.get("/api/platform/diagnostics")
        self.assertEqual(answer.status_code, 200)
        body = answer.json()
        found = {item["id"]: item for item in body["checks"]}
        self.assertEqual(found["platform_store"]["status"], "ok")
        self.assertIn("5", found["task_store"]["detail"])
        self.assertIn("startup", body)
        packed = self.client.get("/api/platform/diagnostics/bundle")
        self.assertEqual(packed.status_code, 200)
        self.assertEqual(packed.headers["content-type"], "application/zip")
        self.assertRegex(packed.headers["content-disposition"], r'filename="diagnostics-\d{8}-\d{6}\.zip"')
        with zipfile.ZipFile(io.BytesIO(packed.content)) as archive:
            self.assertIn("report.json", archive.namelist())


if __name__ == "__main__":
    unittest.main()
