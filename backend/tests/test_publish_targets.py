import json
import tempfile
import unittest
from pathlib import Path

from app.core import publish_targets as pt
from app.repository.task_repo import TaskRepository
from app.service.drama_service import DramaService

FILMS = [pt.Film(1, "贱籍碰剑，断手", "http://localhost:8000/media/e1.mp4", 368.0), pt.Film(2, "你这双手", "http://localhost:8000/media/e2.mp4", 95.0)]


def _build(platform_id, copy=None, **overrides):
    values = {"films": FILMS, "aspect": "9:16", "fallback_title": "拭剑奴", "fallback_description": "《拭剑奴》"}
    values.update(overrides)
    return pt.build_package(pt.platform(platform_id), copy, **values)


class PackageTests(unittest.TestCase):
    def test_the_catalog_matches_the_share_panel(self):
        self.assertEqual(pt.PLATFORM_IDS, ("iqiyi", "tencent", "youku", "douyin", "youtube", "dramabox"))
        self.assertIsNone(pt.platform("dramabox").upload_url, "DramaBox has no public upload page")

    def test_a_long_title_is_cut_to_the_platform_limit_and_flagged(self):
        package = _build("douyin", {"title": "剑" * 50, "description": "冲突", "tags": ["武侠", "#复仇", "武侠"]})

        self.assertLessEqual(len(package["title"]), 30)
        self.assertEqual(package["tags"], ["武侠", "复仇"])
        self.assertTrue(any("标题超过 30 字" in check["text"] for check in package["checks"]))

    def test_the_description_carries_no_ai_statement(self):
        zh = _build("iqiyi", {"title": "拭剑奴", "description": "长" * 400})
        en = _build("youtube", {"title": "The Sword Wiper", "description": "A servant's hands."})

        self.assertLessEqual(len(zh["description"]), 300)
        self.assertNotIn("AI", zh["description"])
        self.assertEqual(en["description"], "A servant's hands.")

    def test_an_ai_statement_the_model_wrote_is_taken_out(self):
        zh = _build("iqiyi", {"title": "拭剑奴", "description": "奴仆拭剑。本片含AI生成内容。真相浮现。"})
        en = _build("youtube", {"title": "Sword", "description": "A servant wipes a sword. Contains AI-generated content."})

        self.assertEqual(zh["description"], "奴仆拭剑。真相浮现。")
        self.assertEqual(en["description"], "A servant wipes a sword.")

    def test_the_checklist_does_not_ask_for_an_ai_label_on_chinese_platforms(self):
        for platform_id in ("iqiyi", "tencent", "youku", "douyin"):
            self.assertFalse([note for note in pt.platform(platform_id).notes if "AI" in note])

    def test_blocking_problems_make_a_package_not_ready(self):
        wrong_aspect = _build("douyin", {"title": "拭剑奴"}, aspect="16:9")
        no_film = _build("youku", {"title": "拭剑奴"}, films=[])

        self.assertFalse(wrong_aspect["ready"])
        self.assertFalse(no_film["ready"])
        self.assertTrue(_build("douyin", {"title": "拭剑奴"})["ready"])

    def test_youtube_notes_episodes_longer_than_a_short(self):
        checks = [check["text"] for check in _build("youtube", {"title": "x"})["checks"]]

        self.assertTrue(any("第 1 集 368 秒" in text for text in checks))
        self.assertFalse(any("第 2 集" in text for text in checks))

    def test_missing_copy_falls_back_and_says_so(self):
        package = _build("tencent", None)

        self.assertEqual(package["title"], "拭剑奴")
        self.assertTrue(any("模型未返回" in check["text"] for check in package["checks"]))

    def test_model_json_is_read_from_a_fenced_answer_and_unknown_keys_dropped(self):
        text = '```json\n{"douyin": {"title": "a"}, "weibo": {"title": "b"}}\n```'

        self.assertEqual(pt.parse_copy(text), {"douyin": {"title": "a"}})
        self.assertEqual(pt.parse_copy("不是 JSON"), {})


class _Gateway:
    def __init__(self, answer):
        self.answer = answer
        self.prompts = []

    def call_llm(self, model, system_prompt, user_prompt, title, *args, **kwargs):
        self.prompts.append(user_prompt)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.repo.save_task("pub-1", {
            "task_id": "pub-1", "status": "idle", "logs": {},
            "config": {"llm_model": "deepseek", "title_suggestion": "武侠短剧"},
            "assets": {
                "1": "贱籍少年拭剑为生，一次碰剑被断手。",
                "2_screenwriting": {"episodes": {"1": {"plan": {"title": "第1集 贱籍碰剑，断手"}}}},
                "7": {"aspect_ratio": "9:16", "episodes": [{"episode": 1, "final_video_url": "http://localhost:8000/media/none.mp4"}]},
                "8": {"pr_content": "🔥 抖音爆款大字标题：拭剑奴\n📌 黄金引流文案：‘x’"},
            },
        })
        self.service = DramaService()
        self.service.repo = self.repo

    def tearDown(self):
        self.temp.cleanup()

    def test_prepare_writes_copy_for_the_chosen_platforms_and_keeps_it(self):
        self.service.gateway = _Gateway(json.dumps({
            "douyin": {"title": "贱籍少年拭剑，一碰断手", "description": "他只配擦剑。", "tags": ["武侠"]},
            "youtube": {"title": "The Sword Wiper", "description": "He was only allowed to wipe swords.", "tags": ["wuxia"]},
        }, ensure_ascii=False))

        result = self.service.prepare_publish("pub-1", ["youtube", "douyin", "weibo"])

        self.assertEqual(result["prepared"]["platforms"], ["douyin", "youtube"], "catalog order, unknown ids dropped")
        douyin, youtube = result["prepared"]["packages"]
        self.assertEqual(douyin["title"], "贱籍少年拭剑，一碰断手")
        self.assertEqual(youtube["episodes"][0]["title"], "贱籍碰剑，断手")
        self.assertIn("剧名：拭剑奴", self.service.gateway.prompts[0])
        stored = self.repo.get_task("pub-1")["assets"]["8_publish"]
        self.assertEqual([item["platform"] for item in stored["packages"]], ["douyin", "youtube"])
        self.assertEqual(self.service.get_publish_preparation("pub-1")["prepared"], stored)

    def test_a_failed_copy_call_still_prepares_from_the_title(self):
        self.service.gateway = _Gateway(RuntimeError("down"))

        package = self.service.prepare_publish("pub-1", ["iqiyi"])["prepared"]["packages"][0]

        self.assertEqual(package["title"], "拭剑奴")
        self.assertNotIn("AI生成", package["description"])

    def test_no_platform_is_refused(self):
        self.service.gateway = _Gateway("{}")

        with self.assertRaises(ValueError):
            self.service.prepare_publish("pub-1", [])


if __name__ == "__main__":
    unittest.main()
