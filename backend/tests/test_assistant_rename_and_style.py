# -*- coding: utf-8 -*-
"""助手的三个工具：先看改名会影响什么、确认后改名、把「以后都这样写」记到账号上。"""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from app.core import asset_identity, prompt_preferences
from app.core.agent_tools import catalog
from app.core.prompt_preferences import Preference, PreferenceError
from app.platform.store import PlatformStore
from app.repository.task_repo import TaskRepository
from app.service.drama_service import DramaService

from tests.test_asset_identity import _task


class RenameToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.repo.save_task("id-1", {**_task(), "owner_user_id": "u"})
        self.service = DramaService()
        self.service.repo = self.repo

    def call(self, tool, /, **arguments):
        return catalog.call(tool, {"task_id": "id-1", **arguments}, service=self.service, user={"user_id": "u"})

    def test_the_preview_counts_what_a_rename_would_touch_and_changes_nothing(self):
        result = self.call("preview_asset_rename", kind="character", name="林夏", new_name="铁蛋")
        self.assertTrue(result["ok"], result)
        expected = asset_identity.preview_rename(_task(), "character", "林夏", "铁蛋")
        self.assertEqual(result["result"]["total_references"], expected.total())
        self.assertEqual(result["result"]["episodes"], expected.episodes)
        self.assertIn("林夏", self.repo.get_task("id-1")["assets"]["3_sheets"])

    def test_the_rename_follows_every_reference_and_keeps_the_old_name_as_an_alias(self):
        result = self.call("rename_project_asset", kind="character", name="林夏", new_name="铁蛋")
        self.assertTrue(result["ok"], result)
        stored = self.repo.get_task("id-1")
        self.assertIn("铁蛋", stored["assets"]["2"])
        self.assertNotIn("林夏", stored["assets"]["2"])
        self.assertIn("林夏", result["result"]["aliases"])

    def test_a_name_that_is_taken_or_missing_is_an_answer_not_a_crash(self):
        taken = self.call("preview_asset_rename", kind="character", name="林夏", new_name="周教授")
        self.assertFalse(taken["ok"])
        self.assertTrue(taken["error"])
        missing = self.call("rename_project_asset", kind="prop", name="没有这件东西", new_name="新名字")
        self.assertFalse(missing["ok"])

    def test_the_two_tools_say_what_they_are(self):
        tools = {tool["name"]: tool for tool in catalog.describe()}
        self.assertIn("只数不改", tools["preview_asset_rename"]["description"])
        self.assertIn("用户明确同意之后才调用", tools["rename_project_asset"]["description"])


class StyleMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.url = f"sqlite+aiosqlite:///{Path(self.temp.name) / 'p.sqlite3'}"

        async def prepare() -> str:
            store = PlatformStore(self.url)
            await store.create_schema()
            user, _ = await store.create_user(email="style@example.com", phone=None, password="user-password-strong")
            await store.close()
            return user.id

        self.owner = asyncio.run(prepare())
        patcher = mock.patch("app.settings.database_url", return_value=self.url)
        patcher.start()
        self.addCleanup(patcher.stop)

    def saved(self):
        return asyncio.run(prompt_preferences._read(self.owner))

    def test_a_line_said_in_chat_is_kept_for_the_account_and_a_second_one_joins_it(self):
        first = catalog.call("remember_my_style", {"text": "台词默认走女频爽剧风格，节奏要快"}, service=None, user={"user_id": self.owner})
        self.assertTrue(first["ok"], first)
        self.assertEqual((first["result"]["agent"], first["result"]["label"], first["result"]["mode"]), ("writer", "编剧", "append"))
        prompt_preferences.add_line(self.owner, "writer", "台词里不要成语")
        prompt_preferences.add_line(self.owner, "writer", "台词里不要成语")
        self.assertEqual(self.saved(), {"writer": Preference("append", "台词默认走女频爽剧风格，节奏要快\n台词里不要成语")})

    def test_a_stage_the_creator_rewrote_keeps_their_text_and_gains_the_line(self):
        async def rewrite():
            store = PlatformStore(self.url)
            await store.set_prompt_preference(self.owner, "director_plan", "rewrite", "按纪实片的路子定调")
            await store.close()

        asyncio.run(rewrite())
        prompt_preferences.add_line(self.owner, "director_plan", "全片冷色")
        self.assertEqual(self.saved()["director_plan"], Preference("rewrite", "按纪实片的路子定调\n全片冷色"))

    def test_an_unknown_stage_an_empty_line_and_no_account_are_refused(self):
        with self.assertRaises(PreferenceError):
            prompt_preferences.add_line(self.owner, "nope", "x")
        with self.assertRaises(PreferenceError):
            prompt_preferences.add_line(self.owner, "writer", "   ")
        with self.assertRaises(PreferenceError):
            prompt_preferences.add_line("", "writer", "x")
        answer = catalog.call("remember_my_style", {"text": "x" * 2000}, service=None, user={"user_id": self.owner})
        self.assertFalse(answer["ok"])
        self.assertEqual(self.saved(), {})


if __name__ == "__main__":
    unittest.main()
