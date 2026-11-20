import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import user_api
from app.api.auth_api import get_current_user
from app.core import prompt_data, prompt_preferences as preferences
from app.core.prompt_preferences import Preference
from app.platform.dependencies import get_platform_store
from app.platform.store import PlatformStore
from app.service import harness_evolution, screenwriting_service

PLATFORM = "Role: 平台的总导演\nMethodology: 平台的方法。\n\n"


class LayerTest(unittest.TestCase):
    def test_following_sends_the_platform_text_untouched(self):
        for choice in (None, Preference(), Preference("append", ""), Preference("follow", "leftover")):
            self.assertIs(preferences.creative_layer("director_plan", PLATFORM, choice), PLATFORM)

    def test_appending_keeps_the_platform_method_and_adds_the_creators_lines(self):
        layer = preferences.creative_layer("director_plan", PLATFORM, Preference("append", "少用旁白，多用动作交代"))
        self.assertTrue(layer.startswith(PLATFORM.rstrip("\n")))
        self.assertIn("少用旁白，多用动作交代", layer)
        self.assertLess(layer.index("平台的方法"), layer.index("少用旁白"))
        self.assertLess(layer.index("少用旁白"), layer.index(prompt_data.text("prompt_preferences", "guard")))
        self.assertTrue(layer.endswith("\n\n"))

    def test_rewriting_replaces_the_method_and_keeps_the_guard(self):
        layer = preferences.creative_layer("director_plan", PLATFORM, Preference("rewrite", "按纪实片的路子定调"))
        self.assertNotIn("平台的方法", layer)
        self.assertIn("按纪实片的路子定调", layer)
        self.assertIn(prompt_data.text("prompt_preferences", "guard"), layer)

    def test_a_rewrite_keeps_the_sentence_the_stage_protects(self):
        layer = preferences.creative_layer("promo", PLATFORM, Preference("rewrite", "标题要冷，不喊口号"))
        self.assertIn(preferences.operation("promo").protected, layer)
        self.assertIn("不得制造不存在的剧情", layer)

    def test_a_stage_that_offers_no_rewrite_falls_back_to_the_platform_text(self):
        for stage in ("writer", "character_design", "storyboard"):
            self.assertNotIn("rewrite", preferences.operation(stage).modes)
            self.assertTrue(preferences.operation(stage).why_no_rewrite)
            self.assertEqual(preferences.creative_layer(stage, PLATFORM, Preference("rewrite", "整段换掉")), PLATFORM)

    def test_an_append_on_a_stage_with_no_method_of_its_own_is_just_the_block(self):
        layer = preferences.creative_layer("storyboard", "", Preference("append", "多给手部特写"))
        self.assertTrue(layer.startswith(prompt_data.value("prompt_preferences", "headings")["append"]))
        self.assertEqual(preferences.creative_layer("storyboard", "", None), "")


class NormaliseTest(unittest.TestCase):
    def test_what_is_stored_is_trimmed_and_free_of_control_characters(self):
        choice = preferences.normalise("director_plan", "append", "  第一条\n\t第二条\x00\x07  ")
        self.assertEqual(choice, Preference("append", "第一条\n\t第二条"))
        self.assertEqual(preferences.normalise("writer", "follow", "ignored"), Preference())

    def test_what_does_not_fit_is_refused_with_a_reason(self):
        limit = preferences.text_limit()
        cases = (
            ("nowhere", "append", "x", "没有这个环节"),
            ("writer", "louder", "x", "没有这种方式"),
            ("writer", "rewrite", "x", "只能追加"),
            ("promo", "append", "  \n ", "要写上内容"),
            ("promo", "rewrite", "字" * (limit + 1), str(limit)),
        )
        for stage, mode, text, said in cases:
            with self.assertRaises(preferences.PreferenceError) as refused:
                preferences.normalise(stage, mode, text)
            self.assertIn(said, str(refused.exception))

    def test_the_catalogue_shows_every_stage_with_the_accounts_choice(self):
        shown = preferences.catalogue({"promo": Preference("rewrite", "标题要冷"), "writer": Preference("rewrite", "不该在")})
        by_id = {item["id"]: item for item in shown["operations"]}
        self.assertEqual([item["stage"] for item in shown["operations"]], [1, 2, 3, 4, 8])
        self.assertEqual((by_id["promo"]["mode"], by_id["promo"]["text"]), ("rewrite", "标题要冷"))
        self.assertEqual((by_id["writer"]["mode"], by_id["writer"]["text"]), ("follow", ""))
        self.assertEqual(by_id["director_plan"]["platform_text"], prompt_data.text("agent_prompts", "executive_director").strip())
        self.assertEqual(by_id["storyboard"]["platform_text"], "")
        self.assertEqual([mode["id"] for mode in shown["modes"]], ["follow", "append", "rewrite"])


class WriterPromptTest(unittest.TestCase):
    def test_the_writers_stages_carry_the_preference_and_the_extract_pass_does_not(self):
        plain = screenwriting_service.writer_system_prompts("role")
        mine = screenwriting_service.writer_system_prompts("role", preference=Preference("append", "台词里不要成语"))
        self.assertEqual(screenwriting_service.writer_system_prompts("role", preference=Preference()), plain)
        for stage in ("ledger", "plan", "prose", "visual"):
            self.assertIn("台词里不要成语", mine[stage])
            self.assertIn(screenwriting_service.WRITER_METHODOLOGY, mine[stage])
            self.assertNotIn("\n\n\n", mine[stage][: mine[stage].index("台词里不要成语") + 200])
        self.assertEqual(mine["extract"], plain["extract"])


class ReadingForATaskTest(unittest.TestCase):
    def test_no_owner_or_switched_off_means_every_stage_follows(self):
        with mock.patch.object(preferences, "_read") as read, mock.patch.dict(os.environ, {"PROMPT_PREFERENCES": "on"}):
            self.assertEqual(preferences.for_task({"task_id": "t"}), {})
            self.assertEqual(preferences.for_task(None), {})
        with mock.patch.object(preferences, "_read") as off, mock.patch.dict(os.environ, {"PROMPT_PREFERENCES": "off"}):
            self.assertEqual(preferences.for_task({"owner_user_id": "u1"}), {})
        read.assert_not_called()
        off.assert_not_called()

    def test_a_store_that_cannot_be_read_never_stops_the_stage(self):
        async def broken(_owner):
            raise ConnectionError("no route")

        with mock.patch.object(preferences, "_read", broken), mock.patch.dict(os.environ, {"PROMPT_PREFERENCES": "on"}), \
                self.assertLogs("app.core.prompt_preferences", level="WARNING"):
            self.assertEqual(preferences.for_task({"owner_user_id": "u1"}), {})

    def test_the_owners_rows_are_read_from_the_store_also_under_a_running_loop(self):
        with tempfile.TemporaryDirectory() as folder:
            url = f"sqlite+aiosqlite:///{Path(folder) / 'p.sqlite3'}"

            async def prepare() -> str:
                store = PlatformStore(url)
                await store.create_schema()
                user, _ = await store.create_user(email="pref@example.com", phone=None, password="user-password-strong")
                await store.set_prompt_preference(user.id, "director_plan", "rewrite", "按纪实片的路子定调")
                await store.set_prompt_preference(user.id, "writer", "append", "台词里不要成语")
                await store.set_prompt_preference(user.id, "writer", "append", "台词里不要成语，也不要网络用语")
                await store.set_prompt_preference(user.id, "promo", "append", "先留着")
                await store.set_prompt_preference(user.id, "promo", "follow", "")
                await store.set_prompt_preference(user.id, "storyboard", "rewrite", "旧版本留下的、现在不开放的选择")
                await store.close()
                return user.id

            owner = asyncio.run(prepare())
            expected = {
                "director_plan": Preference("rewrite", "按纪实片的路子定调"),
                "writer": Preference("append", "台词里不要成语，也不要网络用语"),
            }
            with mock.patch("app.settings.database_url", return_value=url), mock.patch.dict(os.environ, {"PROMPT_PREFERENCES": "on"}):
                self.assertEqual(preferences.for_task({"owner_user_id": owner}), expected)

                async def inside_a_loop():
                    return preferences.for_task({"owner_user_id": owner})

                self.assertEqual(asyncio.run(inside_a_loop()), expected)
                self.assertEqual(preferences.for_task({"owner_user_id": "someone-else"}), {})


class SharedLearningTest(unittest.TestCase):
    def test_a_call_that_carried_a_personal_preference_is_not_studied(self):
        self.assertTrue(preferences.personal(Preference("append", "x")))
        self.assertFalse(preferences.personal(Preference()))
        self.assertFalse(preferences.personal(None))
        with mock.patch.dict(os.environ, {"HARNESS_EVOLUTION": "aside"}), \
                mock.patch.object(harness_evolution, "wants", side_effect=AssertionError("must not get this far")):
            started = harness_evolution.study_stage(
                mock.Mock(), task_id="t", stage=1, domain="古装", model="m", title="片", system_prompt="s", request="r",
                output="方案", personal=True,
            )
        self.assertFalse(started)


class StageWiringTest(unittest.TestCase):
    def test_every_stage_that_offers_a_preference_reads_it_where_its_method_is_written(self):
        source = (Path(__file__).resolve().parents[1] / "app/service/drama_service.py").read_text(encoding="utf-8")
        for stage in ("director_plan", "writer", "character_design", "storyboard", "promo"):
            self.assertRegex(source, r'prompt_preferences\.creative_layer\(\s*"' + stage + '"')
            self.assertIn(f'preferences.get("{stage}")', source)
        self.assertIn('preference=prompt_preferences.for_task(task).get("writer")', source)
        for stage in ("director_plan", "character_design", "promo", "storyboard"):
            self.assertIn(f'prompt_preferences.personal(preferences.get("{stage}"))', source)


class PreferenceApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = PlatformStore(f"sqlite+aiosqlite:///{Path(self.temp.name) / 'api.sqlite3'}")

        async def prepare():
            await self.store.create_schema()
            self.user, _ = await self.store.create_user(email="mine@example.com", phone=None, password="user-password-strong")
            self.other, _ = await self.store.create_user(email="other@example.com", phone=None, password="user-password-strong")

        asyncio.run(prepare())
        self.app = FastAPI()
        self.app.include_router(user_api.router)
        self.app.dependency_overrides[get_platform_store] = lambda: self.store
        self.client = TestClient(self.app)

    def _sign_in(self, user):
        self.app.dependency_overrides[get_current_user] = lambda: {"user_id": user.id, "username": user.username, "permissions": []}

    def _by_id(self, body):
        return {item["id"]: item for item in body["operations"]}

    def test_it_needs_a_signed_in_account(self):
        self.assertEqual(self.client.get("/api/users/me/prompt-preferences").status_code, 401)
        self.assertEqual(self.client.put("/api/users/me/prompt-preferences/promo", json={"mode": "follow"}).status_code, 401)

    def test_an_account_saves_changes_and_clears_its_own_choice(self):
        self._sign_in(self.user)
        start = self._by_id(self.client.get("/api/users/me/prompt-preferences").json())
        self.assertTrue(all(item["mode"] == "follow" for item in start.values()))
        saved = self.client.put("/api/users/me/prompt-preferences/promo", json={"mode": "rewrite", "text": " 标题要冷 "})
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(self._by_id(saved.json())["promo"]["text"], "标题要冷")
        again = self._by_id(self.client.get("/api/users/me/prompt-preferences").json())
        self.assertEqual((again["promo"]["mode"], again["promo"]["text"]), ("rewrite", "标题要冷"))
        cleared = self.client.put("/api/users/me/prompt-preferences/promo", json={"mode": "follow"})
        self.assertEqual(self._by_id(cleared.json())["promo"]["mode"], "follow")
        self._sign_in(self.other)
        self.client.put("/api/users/me/prompt-preferences/writer", json={"mode": "append", "text": "别人的偏好"})
        self._sign_in(self.user)
        mine = self._by_id(self.client.get("/api/users/me/prompt-preferences").json())
        self.assertEqual(mine["writer"]["mode"], "follow")

    def test_a_choice_the_stage_does_not_offer_is_refused(self):
        self._sign_in(self.user)
        refused = self.client.put("/api/users/me/prompt-preferences/storyboard", json={"mode": "rewrite", "text": "整段换掉"})
        self.assertEqual(refused.status_code, 422)
        self.assertIn("只能追加", refused.json()["detail"])
        self.assertEqual(self.client.put("/api/users/me/prompt-preferences/nowhere", json={"mode": "append", "text": "x"}).status_code, 422)
        self.assertEqual(self.client.put("/api/users/me/prompt-preferences/promo", json={"mode": "append", "text": ""}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
