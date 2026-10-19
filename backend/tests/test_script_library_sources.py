"""The script library feeds stage 2: whole-source files are cut into episodes, own-source files become episodes of their own."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core.screenwriting.engine import ScreenwritingEngine
from app.core.screenwriting.renderer import episode_body, render_screenplay
from app.repository.task_repo import TaskRepository
from app.service import screenwriting_service as screenwriting
from app.service.drama_service import DramaService
from tests.test_screenwriting_engine import MINIATURE_EPISODES, FakeModel, _scene

NOVEL = (
    "夜雨压着宫城，东宫檐角的铜铃被风吹得乱响。太子萧景琰跪在先帝灵前。"
    "门外传来内侍的通报声，宣的是摄政王的令。萧景琰没有碰那封密折，只抬眼望向殿门外。"
    "殿内只剩母后沈氏，她将一件旧狐裘搭到萧景琰肩上。屏风后走出一个驼背老人，竟是太傅顾行舟。"
)
EPISODE_PLOTS = [
    "萧景琰被禁足东宫，太傅顾行舟深夜送来铜虎符，指明太庙第七龛藏着先帝遗诏。",
    "萧擎在承天殿当堂议罪，萧景琰亮出虎符，百官哗然，太庙之门被连夜封锁。",
]


def _engine(model: FakeModel) -> ScreenwritingEngine:
    return ScreenwritingEngine(model, video_model="seedance2.0", attempts=3, system_prompt="SYS", style="写实电影感", episode_shape=MINIATURE_EPISODES)


class OwnSourceEpisodeEngineTests(unittest.TestCase):
    def test_own_source_episodes_follow_the_cut_ones_and_keep_their_own_text(self):
        model = FakeModel()
        own = [{"text": plot, "name": f"episode_{index}.txt"} for index, plot in enumerate(EPISODE_PLOTS, start=1)]

        state = _engine(model).write(title="退位杀机", director_plan="", episode_count=4, source_text=NOVEL, own_episodes=own)

        origins = [(entry["episode"], entry["source_origin"]) for entry in state["ledger"]]
        self.assertEqual(origins[:2], [(1, "cut"), (2, "cut")])
        self.assertEqual(origins[2:], [(3, "own"), (4, "own")])
        self.assertEqual(state["ledger"][2]["source_name"], "episode_1.txt")
        self.assertEqual(state["ledger"][2]["source_kind"], "novel")
        # Every episode was written, and an own-source episode reads as its own upload.
        self.assertEqual(sorted(int(key) for key in state["episodes"]), [1, 2, 3, 4])
        self.assertEqual(episode_body(state, 3), EPISODE_PLOTS[0])
        self.assertIn("第3集", render_screenplay(state))
        self.assertIn(EPISODE_PLOTS[1], render_screenplay(state))
        # Planning the whole source consumed only the whole source: its spans never reach the own texts.
        for entry in state["ledger"][:2]:
            span = entry["source_range"]
            self.assertLessEqual(span["end"], len(state["source_text"]))

    def test_the_whole_source_is_cut_into_whatever_the_own_episodes_leave(self):
        model = FakeModel()
        own = [{"text": plot, "name": f"ep{index}.txt"} for index, plot in enumerate(EPISODE_PLOTS, start=1)]

        state = _engine(model).write(title="退位杀机", director_plan="", episode_count=2, source_text=NOVEL, own_episodes=own)

        # Two episodes requested and two arrived with their own text: the whole source still has to go
        # somewhere, so it is cut as the story dictates and the count grows to fit.
        origins = [entry["source_origin"] for entry in state["ledger"]]
        self.assertGreaterEqual(origins.count("cut"), 1)
        self.assertEqual(origins[-2:], ["own", "own"])
        self.assertTrue(all(origin == "cut" for origin in origins[:-2]))
        self.assertEqual(state["episode_count"], len(state["ledger"]))

    def test_own_episodes_alone_make_a_project_without_any_whole_source(self):
        model = FakeModel()
        own = [{"text": plot, "name": f"episode_{index}.txt"} for index, plot in enumerate(EPISODE_PLOTS, start=1)]

        state = _engine(model).write(title="退位杀机", director_plan="三幕大纲", episode_count=2, own_episodes=own)

        self.assertEqual(state["source_kind"], "novel")
        self.assertEqual([entry["source_origin"] for entry in state["ledger"]], ["own", "own"])
        self.assertIsNone(state["source_text"])
        self.assertEqual(episode_body(state, 2), EPISODE_PLOTS[1])

    def test_an_own_screenplay_episode_is_extracted_verbatim_while_a_novel_one_is_adapted(self):
        model = FakeModel()
        screenplay = "第1集 对峙\n场景1：地下实验室 夜 内景\n林夏：你到底瞒了什么？\n周教授：现在回头还来得及。"
        model.plan_overrides[1] = lambda attempt, prompt: json.dumps(
            {"title": "对峙", "scenes": [_scene(1, 1), _scene(1, 2, speaker="周教授", text="现在回头还来得及。")]}, ensure_ascii=False,
        )

        state = _engine(model).write(
            title="暗室回声", director_plan="", episode_count=1,
            own_episodes=[{"text": screenplay, "name": "ep1.txt", "source_kind": "screenplay"}],
        )

        self.assertEqual(state["ledger"][0]["source_kind"], "screenplay")
        plan_prompt = next(call["prompt"] for call in model.calls if "scene_description" in call["prompt"])
        self.assertIn("**提取**", plan_prompt)

    def test_a_mixed_project_reads_as_a_novel(self):
        model = FakeModel()
        screenplay = "第1集 对峙\n场景1：地下实验室 夜 内景\n林夏：你到底瞒了什么？"
        model.plan_overrides[1] = lambda attempt, prompt: json.dumps({"title": "对峙", "scenes": [_scene(1, 1)]}, ensure_ascii=False)

        state = _engine(model).write(
            title="暗室回声", director_plan="", episode_count=2,
            own_episodes=[{"text": screenplay, "name": "a.txt", "source_kind": "screenplay"}, {"text": EPISODE_PLOTS[0], "name": "b.txt"}],
        )

        self.assertEqual(state["source_kind"], "novel")
        self.assertEqual([entry["source_kind"] for entry in state["ledger"]], ["screenplay", "novel"])


class LibraryResolutionTests(unittest.TestCase):
    def test_roles_are_read_from_file_names_and_people_may_overrule_them(self):
        self.assertEqual(screenwriting.document_role_for_name("story.txt"), "source")
        self.assertEqual(screenwriting.document_role_for_name("全本小说.md"), "source")
        self.assertEqual(screenwriting.document_role_for_name("episode_3.txt"), "episode")
        self.assertEqual(screenwriting.document_role_for_name("第12集.txt"), "episode")
        self.assertEqual(screenwriting.document_role_for_name("人物设定.md"), "reference")

    def test_own_source_files_are_ordered_by_the_number_in_their_name_then_by_upload(self):
        documents = [
            {"id": "a", "name": "episode_5.txt", "role": "episode"},
            {"id": "b", "name": "episode_3.txt", "role": "episode"},
            {"id": "c", "name": "story.txt", "role": "source"},
            {"id": "d", "name": "episode_1.txt", "role": "episode"},
            {"id": "e", "name": "notes.txt", "role": "episode"},
            {"id": "f", "name": "episode_4.txt", "role": "episode", "order": 0},
        ]

        ordered = [item["id"] for item in screenwriting.ordered_documents(documents, "episode")]

        self.assertEqual(ordered, ["f", "d", "b", "a", "e"])
        self.assertEqual([item["id"] for item in screenwriting.ordered_documents(documents, "source")], ["c"])

    def test_the_library_wins_over_the_single_uploaded_script(self):
        task = {
            "config": {"script_content": "第1集 旧的单文件剧本\n林夏：旧台词。"},
            "assets": {"2_documents": [
                {"id": "1", "name": "story.txt", "role": "source", "content": NOVEL},
                {"id": "2", "name": "episode_2.txt", "role": "episode", "content": EPISODE_PLOTS[1]},
                {"id": "3", "name": "episode_1.txt", "role": "episode", "content": EPISODE_PLOTS[0]},
                {"id": "4", "name": "设定.md", "role": "reference", "content": "不进入源文"},
            ]},
        }

        whole, kind, own = screenwriting.source_for_task(task)

        self.assertEqual(whole, NOVEL)
        self.assertEqual(kind, "novel")
        self.assertEqual([item["name"] for item in own], ["episode_1.txt", "episode_2.txt"])
        self.assertEqual([item["source_kind"] for item in own], ["novel", "novel"])

    def test_without_library_sources_the_single_uploaded_script_still_counts(self):
        task = {"config": {"script_content": "第1集 对峙\n场景1：地下实验室\n林夏：你到底瞒了什么？\n周教授：回头。"}, "assets": {"2_documents": [
            {"id": "4", "name": "设定.md", "role": "reference", "content": "不进入源文"},
        ]}}

        whole, kind, own = screenwriting.source_for_task(task)

        self.assertTrue(whole.startswith("第1集"))
        self.assertEqual(kind, "screenplay")
        self.assertEqual(own, [])


class LibraryServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.repo.save_task("lib-1", {"task_id": "lib-1", "status": "idle", "config": {"title_suggestion": "退位杀机", "episode_count": 3}, "assets": {}, "logs": {}})
        self.service = DramaService()
        self.service.repo = self.repo

    def test_imported_files_get_a_role_a_genre_and_a_broadcast_position(self):
        self.service.create_script_document("lib-1", name="episode_2.txt", content=EPISODE_PLOTS[1])
        self.service.create_script_document("lib-1", name="story.txt", content=NOVEL)
        self.service.create_script_document("lib-1", name="episode_1.txt", content=EPISODE_PLOTS[0])
        self.service.create_script_document("lib-1", name="人物小传.md", content="参考")

        documents = {item["name"]: item for item in self.service.list_script_documents("lib-1")}

        self.assertEqual(documents["story.txt"]["role"], "source")
        self.assertEqual(documents["story.txt"]["source_kind"], "novel")
        self.assertEqual(documents["人物小传.md"]["role"], "reference")
        self.assertIsNone(documents["人物小传.md"]["source_kind"])
        self.assertEqual((documents["episode_1.txt"]["position"], documents["episode_2.txt"]["position"]), (1, 2))
        self.assertIsNone(documents["episode_1.txt"]["episode"])

    def test_changing_a_source_document_marks_the_written_plan_stale(self):
        created = self.service.create_script_document("lib-1", name="story.txt", content=NOVEL)
        task = self.repo.get_task("lib-1")
        task["assets"][screenwriting.STATE_KEY] = {"engine": screenwriting.ENGINE_NAME, "stale": False, "stale_reason": None, "episodes": {"1": {}}, "ledger": []}
        self.repo.save_task("lib-1", task)

        self.service.update_script_document("lib-1", created["id"], content=NOVEL + "尾声。")
        state = screenwriting.state_of(self.repo.get_task("lib-1"))
        self.assertTrue(state["stale"])
        self.assertIn("story.txt", state["stale_reason"])

        state["stale"] = False
        self.repo.save_task("lib-1", self.repo.get_task("lib-1") | {"assets": {**self.repo.get_task("lib-1")["assets"], screenwriting.STATE_KEY: state}})
        reference = self.service.create_script_document("lib-1", name="备注.md", content="参考")
        self.service.update_script_document("lib-1", reference["id"], content="改了参考资料")
        self.assertFalse(screenwriting.state_of(self.repo.get_task("lib-1"))["stale"])

        self.service.update_script_document("lib-1", reference["id"], role="episode")
        self.assertTrue(screenwriting.state_of(self.repo.get_task("lib-1"))["stale"])

    def test_a_role_or_genre_outside_the_vocabulary_is_refused(self):
        with self.assertRaisesRegex(ValueError, "文件角色"):
            self.service.create_script_document("lib-1", name="x.txt", content="y", role="master")
        with self.assertRaisesRegex(ValueError, "体裁"):
            self.service.create_script_document("lib-1", name="x.txt", content="y", role="source", source_kind="poem")

    def test_stage_two_reads_the_library_and_the_ledger_names_each_own_episode(self):
        self.service.create_script_document("lib-1", name="story.txt", content=NOVEL)
        self.service.create_script_document("lib-1", name="episode_1.txt", content=EPISODE_PLOTS[0])
        self.service.create_script_document("lib-1", name="episode_2.txt", content=EPISODE_PLOTS[1])
        task = self.repo.get_task("lib-1")
        task["assets"]["1"] = "导演方案"
        self.repo.save_task("lib-1", task)
        model = FakeModel()

        with (
            patch.object(self.service, "_structured_writer_engine", return_value=_engine(model)),
            patch.object(self.service, "run_real_consistency_check", return_value="QC-OK"),
        ):
            done = self.service._run_structured_writer(task, task["config"], "退位杀机", "realistic", "cinematic", "", "lib-1")

        self.assertTrue(done)
        state = task["assets"][screenwriting.STATE_KEY]
        self.assertEqual([entry["source_origin"] for entry in state["ledger"]], ["cut", "own", "own"])
        self.repo.save_task("lib-1", task)
        documents = {item["name"]: item for item in self.service.list_script_documents("lib-1")}
        self.assertEqual((documents["episode_1.txt"]["episode"], documents["episode_2.txt"]["episode"]), (2, 3))


if __name__ == "__main__":
    unittest.main()
