import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import chapter_assets_api, drama_api
from app.api.auth_api import get_current_user
from app.core import chapter_assets, prompt_data
from app.platform.dependencies import get_platform_store
from app.platform.store import PlatformStore
from app.repository.task_repo import TaskRepository


def answer(characters=(), scenes=(), props=(), drop=()):
    body = {
        "characters": [{"name": name, "aliases": [], "description": f"{name}的样子"} for name in characters],
        "scenes": [{"name": name, "description": f"{name}，夜"} for name in scenes],
        "props": [{"name": name, "aliases": ["旧" + name], "description": ""} for name in props],
    }
    for key in drop:
        body.pop(key)
    return json.dumps(body, ensure_ascii=False)


def task(**assets):
    return {
        "task_id": "ch-1", "owner_user_id": "", "status": "idle",
        "config": {"title_suggestion": "雨巷", "llm_model": "m"}, "assets": dict(assets), "logs": {}, "chat_history": [],
    }


class ChaptersTest(unittest.TestCase):
    def test_library_documents_come_first_in_reading_order(self):
        documents = [
            {"id": "e2", "role": "episode", "name": "第2集", "content": "二"},
            {"id": "s1", "role": "source", "name": "原著第一章", "content": "一", "order": 0},
            {"id": "e1", "role": "episode", "name": "第1集", "content": "一集"},
            {"id": "blank", "role": "source", "name": "空", "content": "  "},
        ]
        found = chapter_assets.chapters(task(**{"2_documents": documents, "2": "第1集 不会用到"}))
        self.assertEqual([item.id for item in found], ["doc:s1", "doc:e1", "doc:e2"])

    def test_a_script_is_split_at_its_episode_headings_else_read_whole(self):
        script = "前言不算\n第1集 雨夜\n林夏进门。\n## 第二集 天亮\n她走了。"
        parts = chapter_assets.chapters(task(**{"2": script}))
        self.assertEqual([(item.id, item.title) for item in parts], [("part:1", "第1集 雨夜"), ("part:2", "第二集 天亮")])
        self.assertTrue(parts[1].text.startswith("## 第二集"))
        whole = chapter_assets.chapters(task(**{"2": "没有分集标题的一段"}))
        self.assertEqual([item.id for item in whole], ["script"])
        self.assertEqual(chapter_assets.chapters(task()), [])
        with self.assertRaises(chapter_assets.ChapterAssetError) as refused:
            chapter_assets.chapter(task(), "script")
        self.assertIn("还没有可以提取的章节", str(refused.exception))


class PromptTest(unittest.TestCase):
    def test_the_contract_comes_last_and_known_names_are_offered(self):
        current = task(**{"2": "第1集\n林夏在码头。", "3_characters": [{"name": "林夏"}],
                          "2_breakdown": {"production_assets": {"scenes": [{"name": "码头"}], "props": []}}})
        system, user = chapter_assets.prompt(current, chapter_assets.chapters(current)[0])
        self.assertTrue(system.endswith(prompt_data.text("chapter_assets", "contract")))
        self.assertIn("林夏", user)
        self.assertIn("码头", user)
        self.assertIn("雨巷", user)

    def test_a_long_chapter_is_cut_with_a_note(self):
        limit = prompt_data.value("chapter_assets", "limits")["chapter_chars"]
        current = task(**{"2": "字" * (limit + 100)})
        _, user = chapter_assets.prompt(current, chapter_assets.chapters(current)[0])
        self.assertIn(prompt_data.text("chapter_assets", "cut_note").strip(), user)
        self.assertLess(user.count("字"), limit + 50)


class ParseTest(unittest.TestCase):
    def test_all_three_lists_are_required_and_may_be_empty(self):
        found = chapter_assets.parse(answer(scenes=["空屋"]))
        self.assertEqual(found["characters"], [])
        self.assertEqual([item["name"] for item in found["scenes"]], ["空屋"])
        for bad, said in (
            ("", "没有给出回答"),
            ("我读完了，没有资产。", "不是 JSON 对象"),
            (answer(scenes=["空屋"], drop=("characters", "props")), "缺了「角色、道具」"),
            (json.dumps({"characters": [], "scenes": "码头", "props": []}), "应当是数组"),
        ):
            with self.assertRaises(chapter_assets.ChapterAssetError) as refused:
                chapter_assets.parse(bad)
            self.assertIn(said, str(refused.exception))

    def test_entries_are_cleaned_deduplicated_and_capped(self):
        cap = prompt_data.value("chapter_assets", "limits")["items_per_list"]
        raw = json.dumps({
            "characters": [{"name": " 林夏 ", "aliases": ["阿夏", "林夏", 3]}, {"name": "林夏"}, {"name": ""}, "路人"],
            "scenes": [{"name": f"地点{index}"} for index in range(cap + 5)],
            "props": [],
        }, ensure_ascii=False)
        found = chapter_assets.parse(f"```json\n{raw}\n```")
        self.assertEqual(found["characters"], [{"name": "林夏", "aliases": ["阿夏"], "description": ""}])
        self.assertEqual(len(found["scenes"]), cap)


class RecordTest(unittest.TestCase):
    def test_chapters_merge_by_name_or_alias_and_settling_moves_an_entry(self):
        current = task(**{"2": "第1集\n一\n第2集\n二"})
        first, second = chapter_assets.chapters(current)
        added = chapter_assets.record(current, first, chapter_assets.parse(answer(["林夏"], ["码头"], ["油灯"])))
        self.assertEqual(added, {"characters": 1, "scenes": 1, "props": 1})
        added = chapter_assets.record(current, second, chapter_assets.parse(answer(["林夏", "沈舟"], [], ["旧油灯"])))
        self.assertEqual(added, {"characters": 1, "scenes": 0, "props": 0})
        shown = chapter_assets.view(current)
        lamp = next(item for item in shown["items"] if item["name"] == "油灯")
        self.assertEqual(lamp["chapters"], ["part:1", "part:2"])
        self.assertEqual([chapter["counts"]["characters"] for chapter in shown["chapters"]], [1, 2])
        self.assertFalse(any(chapter["changed"] for chapter in shown["chapters"]))

        linxia = next(item for item in shown["items"] if item["name"] == "林夏")
        chapter_assets.settle(current, linxia["id"], "dismiss")
        with self.assertRaises(chapter_assets.ChapterAssetError) as refused:
            chapter_assets.settle(current, linxia["id"], "confirm")
        self.assertIn("已经忽略", str(refused.exception))
        chapter_assets.settle(current, linxia["id"], "restore")
        chapter_assets.settle(current, linxia["id"], "confirm", element_id="el-1")
        self.assertEqual(chapter_assets.item(current, linxia["id"])["element_id"], "el-1")
        with self.assertRaises(chapter_assets.ChapterAssetError):
            chapter_assets.settle(current, linxia["id"], "explode")

        current["assets"]["2"] = "第1集\n一改过了\n第2集\n二"
        self.assertTrue(chapter_assets.view(current)["chapters"][0]["changed"])

    def test_an_entry_the_project_already_uses_is_marked_known(self):
        current = task(**{"2": "第1集\n一", "3_characters": [{"name": "林夏"}]})
        chapter_assets.record(current, chapter_assets.chapters(current)[0], chapter_assets.parse(answer(["林夏", "沈舟"])))
        known = {item["name"]: item["known"] for item in chapter_assets.view(current)["items"]}
        self.assertEqual(known, {"林夏": True, "沈舟": False})


class ChapterAssetsApiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = PlatformStore(f"sqlite+aiosqlite:///{Path(self.temp.name) / 'p.sqlite3'}")

        async def prepare():
            await self.store.create_schema()
            self.owner, _ = await self.store.create_user(email="ch@example.com", phone=None, password="user-password-strong")

        asyncio.run(prepare())
        repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        current = task(**{"2": "第1集 雨夜\n林夏在码头点起油灯。\n第2集 天亮\n空屋。"})
        current["owner_user_id"] = self.owner.id
        repo.save_task("ch-1", current)
        for patch in (mock.patch.object(drama_api.service, "repo", repo),):
            patch.start()
            self.addCleanup(patch.stop)
        self.repo = repo
        self.app = FastAPI()
        self.app.include_router(chapter_assets_api.router)
        self.app.dependency_overrides[get_platform_store] = lambda: self.store
        self.app.dependency_overrides[get_current_user] = lambda: {
            "user_id": self.owner.id, "username": self.owner.username, "role": "user", "permissions": [],
        }
        self.client = TestClient(self.app)

    def _extract(self, chapter_id, reply):
        with mock.patch.object(drama_api.service.gateway, "call_llm", return_value=reply) as llm:
            answered = self.client.post("/api/drama/ch-1/chapter-assets/extract", json={"chapter_id": chapter_id})
        return answered, llm

    def test_extract_confirm_and_dismiss(self):
        listed = self.client.get("/api/drama/ch-1/chapter-assets").json()
        self.assertEqual([chapter["id"] for chapter in listed["chapters"]], ["part:1", "part:2"])
        done, llm = self._extract("part:1", answer(["林夏"], ["码头"], ["油灯"]))
        self.assertEqual(done.status_code, 200)
        self.assertEqual(done.json()["added"], {"characters": 1, "scenes": 1, "props": 1})
        self.assertIn("林夏在码头", llm.call_args.args[2])
        items = {item["name"]: item for item in done.json()["items"]}

        confirmed = self.client.post(f"/api/drama/ch-1/chapter-assets/items/{items['油灯']['id']}", json={"action": "confirm"})
        self.assertEqual(confirmed.status_code, 200)
        lamp = next(item for item in confirmed.json()["items"] if item["name"] == "油灯")
        self.assertEqual(lamp["status"], "confirmed")

        async def library():
            element = await self.store.get_element(lamp["element_id"], self.owner.id)
            return element.kind, element.name, element.metadata_json

        kind, name, metadata = asyncio.run(library())
        self.assertEqual((kind, name), ("prop", "油灯"))
        self.assertEqual(metadata["aliases"], ["旧油灯"])
        self.assertIn("ch-1", json.dumps(metadata))
        again = self.client.post(f"/api/drama/ch-1/chapter-assets/items/{items['油灯']['id']}", json={"action": "confirm"})
        self.assertEqual(again.status_code, 422)

        dismissed = self.client.post(f"/api/drama/ch-1/chapter-assets/items/{items['林夏']['id']}", json={"action": "dismiss"})
        self.assertEqual(next(item for item in dismissed.json()["items"] if item["name"] == "林夏")["status"], "dismissed")

    def test_an_answer_missing_a_list_records_nothing(self):
        refused, _ = self._extract("part:2", answer(scenes=["空屋"], drop=("props",)))
        self.assertEqual(refused.status_code, 422)
        self.assertIn("道具", refused.json()["detail"])
        stored = self.repo.get_task("ch-1")
        self.assertNotIn(chapter_assets.KEY, stored["assets"])
        self.assertEqual(self._extract("nowhere", answer())[0].status_code, 422)

    def test_a_chapter_with_no_one_in_it_is_a_success(self):
        done, _ = self._extract("part:2", answer(scenes=["空屋"]))
        self.assertEqual(done.status_code, 200)
        chapter = next(item for item in done.json()["chapters"] if item["id"] == "part:2")
        self.assertEqual(chapter["counts"], {"characters": 0, "scenes": 1, "props": 0})


if __name__ == "__main__":
    unittest.main()
