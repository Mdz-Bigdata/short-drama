import inspect
import unittest

from app.core import line_coverage
from app.service import drama_service

SCENE = {
    "scene_id": "E1S07",
    "dialogue": [
        {"kind": "dialogue", "speaker": "裴仲玄", "text": "谁？", "verbatim": True},
        {"kind": "dialogue", "speaker": "裴仲玄", "text": "谁动的剑？", "verbatim": True},
        {"kind": "voiceover", "speaker": "", "text": "剑，自己动了。", "verbatim": True},
        {"kind": "sfx", "speaker": "", "text": "雷声"},
    ],
}


def shot(dialogue):
    return {"dialogue": dialogue}


class LineCoverageTest(unittest.TestCase):
    def test_a_table_with_every_line_once_and_in_order_passes_however_it_is_written(self):
        tables = (
            [shot("裴仲玄（冷硬压嗓）：{谁？} 停顿一拍 {谁动的剑？}"), shot("旁白：剑，自己动了。")],
            [shot("裴仲玄：「谁？」"), shot("裴仲玄{压低}：谁动——"), shot("的剑？"), shot("旁白：剑，自己动了")],
            [shot("无"), shot("裴仲玄：谁？谁动的剑？／旁白：剑，自己动了。")],
        )
        for table in tables:
            with self.subTest(table=table):
                self.assertEqual(line_coverage.table_issues(table, SCENE), [])

    def test_a_missing_line_names_the_speaker_and_the_words(self):
        issues = line_coverage.table_issues([shot("裴仲玄：谁？"), shot("旁白：剑，自己动了。")], SCENE)
        self.assertEqual(len(issues), 1)
        self.assertIn("裴仲玄", issues[0])
        self.assertIn("「谁动的剑？」", issues[0])
        self.assertIn("没有写进", issues[0])

    def test_lines_out_of_order_and_lines_written_too_often_are_named(self):
        swapped = line_coverage.table_issues([shot("旁白：剑，自己动了。"), shot("裴仲玄：谁？谁动的剑？")], SCENE)
        self.assertEqual(len(swapped), 1)
        self.assertIn("「剑，自己动了。」排在了「谁动的剑？」前面", swapped[0].replace("排在了", "排在了"))
        twice = line_coverage.table_issues([shot("裴仲玄：谁？"), shot("裴仲玄：谁？"), shot("裴仲玄：谁动的剑？"), shot("旁白：剑，自己动了。")], SCENE)
        self.assertEqual(len(twice), 1)
        self.assertIn("出现了 2 次，剧本只说了 1 次", twice[0])

    def test_a_line_the_script_says_twice_may_be_written_twice(self):
        scene = {"dialogue": [{"kind": "dialogue", "speaker": "苏问剑", "text": "伸手。"}, {"kind": "dialogue", "speaker": "苏问剑", "text": "伸手。"}]}
        self.assertEqual(line_coverage.table_issues([shot("苏问剑：「伸手。」"), shot("苏问剑：「伸手。」")], scene), [])

    def test_only_spoken_kinds_count_and_a_scene_without_lines_has_nothing_to_check(self):
        self.assertEqual([text for _, text in line_coverage.scripted_lines(SCENE)], ["谁？", "谁动的剑？", "剑，自己动了。"])
        self.assertEqual(line_coverage.scripted_lines({"dialogue": str(SCENE["dialogue"])})[0], ("裴仲玄", "谁？"))
        self.assertEqual(line_coverage.table_issues([shot("无")], {"dialogue": []}), [])
        self.assertEqual(line_coverage.table_issues([shot("无")], {}), [])

    def test_stage_four_sends_the_table_back_for_it_and_keeps_what_is_left_on_the_board(self):
        board = inspect.getsource(drama_service.DramaService._generate_scene_board)
        self.assertIn("issues = [*issues, *line_coverage.table_issues(drafted, scene)]", board)
        self.assertIn("*line_coverage.table_issues(checked, scene),", board)
        self.assertIn("*group_blocking.table_issues(shots), *line_coverage.table_issues(shots, scene),", board)


if __name__ == "__main__":
    unittest.main()


class StageFourRevisionTest(unittest.TestCase):
    """A table that leaves a scripted line out goes back once with the line named, before any picture is drawn."""

    ROW = "| {i} | {size} | 平视 | Fixed | {desc} | {line} | 环境声 | 6s | 线索 | 林夏 | E1S02 书房 |"

    def table(self, lines):
        rows = [("远景", "烛火暖光里，林夏推门进来，档案柜在画面右侧"), ("中景", "烛火暖光下，林夏走到桌前，把公文包放在桌角"),
                ("近景", "林夏翻开第一页档案，指尖停在一张照片上")]
        return "\n".join(self.ROW.format(i=i, size=size, desc=desc, line=line) for i, ((size, desc), line) in enumerate(zip(rows, lines), start=1))

    def board(self, answers):
        from unittest.mock import patch

        from app.core.model_gateway import ModelGateway
        from app.service.drama_service import DramaService

        service = DramaService.__new__(DramaService)
        service.gateway = ModelGateway.__new__(ModelGateway)
        task = {
            "task_id": "synthetic-line-coverage",
            "assets": {"3_sheets": {"林夏": "https://image.test/lin.png"}, "3_characters": [{"name": "林夏", "desc": "青灰大衣"}]},
            "config": {"llm_model": "m", "image_model": "img", "video_model": "kling-v2"},
        }
        scene = {
            "scene_id": "E1S02", "content": "林夏追查线索", "characters": ["林夏"], "duration": "20s",
            "dialogue": [{"kind": "dialogue", "speaker": "林夏", "text": "又是这张照片。", "verbatim": True}],
        }
        with patch.object(service.gateway, "call_llm", side_effect=list(answers)) as llm, \
             patch.object(service.gateway, "generate_image", return_value=("https://image.test/panel.png", {})), \
             patch.object(service.gateway, "validate_image_request", return_value=None, create=True), \
             patch("app.service.drama_service.load_storyboard_elements", return_value=[]), \
             patch("app.service.drama_service.persist_storyboard_frame", return_value=None), \
             patch("app.service.drama_service.compose_nine_grid", side_effect=lambda images, path: path):
            payload = service._generate_scene_board(
                task, task["config"], scene, sys_prompt="s", storyboard_negative="", title="十二小时", genre="mystery",
                dir_style="noir", shot_style="cinematic", guidance="", char_info=("林夏", "记者", "周教授", "反派"),
            )
        return payload, llm

    def test_the_missing_line_goes_back_and_the_table_that_has_it_is_drawn(self):
        payload, llm = self.board([self.table(["", "", ""]), self.table(["", "", "林夏：又是这张照片。"])])
        self.assertEqual(llm.call_count, 2)
        revision_request = llm.call_args_list[1].args[2]
        self.assertIn("「又是这张照片。」没有写进任何一镜的台词栏", revision_request)
        self.assertTrue(any("又是这张照片" in str(shot.get("dialogue")) for shot in payload["shots"]))
        self.assertFalse([issue for issue in payload["craft_issues"] if "又是这张照片" in issue])

    def test_a_table_that_still_leaves_it_out_keeps_the_issue_on_the_board(self):
        payload, llm = self.board([self.table(["", "", ""]), self.table(["", "", ""])])
        self.assertEqual(llm.call_count, 2)
        self.assertTrue([issue for issue in payload["craft_issues"] if "「又是这张照片。」没有写进" in issue])

    def test_a_table_with_the_line_is_drawn_without_a_second_call(self):
        _, llm = self.board([self.table(["林夏：又是这张照片。", "", ""])])
        self.assertEqual(llm.call_count, 1)
