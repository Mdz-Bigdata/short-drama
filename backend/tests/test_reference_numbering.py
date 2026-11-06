"""A video prompt names each reference image by the position it actually has in the request."""

import unittest

from app.core.asset_mentions import resolve_mentions
from app.core.storyboard_scene_context import compile_scene_context, merge_video_references, panel_context, video_reference_entries
from app.core.video_references import VideoGenerationIntent, VideoReferencePlan, plan_video_references, renumber_reference_mentions
from app.core.panel_still_prompt import compile_panel_still
from app.core.shot_motion_contract import ShotMotionContract
from tests.test_production_contracts import _panel

SHEETS = [("林夏", "https://cdn/linxia.png"), ("周教授", "https://cdn/zhou.png")]
LIBRARY = [{"kind": "scene", "name": "地下实验室", "image_url": "https://cdn/lab.png"}]


def _prompt():
    entries = video_reference_entries(SHEETS, LIBRARY)
    numbers = {name: number for number, (_, name, _) in enumerate(entries, start=1)}
    images, notes = merge_video_references(SHEETS, LIBRARY)
    text = resolve_mentions(f"{notes}。@[林夏]在@[地下实验室]里看向@[周教授]。", numbers)
    return text, images


class RenumberTests(unittest.TestCase):
    def test_before_routing_the_prompt_counts_only_the_identity_images(self):
        text, images = _prompt()
        self.assertIn("林夏（参考图1）", text)
        self.assertIn("周教授（参考图2）", text)
        self.assertIn("地下实验室（参考图3）", text)
        self.assertEqual(images, ["https://cdn/linxia.png", "https://cdn/zhou.png", "https://cdn/lab.png"])

    def test_multi_reference_puts_the_first_frame_ahead_and_every_number_moves_with_it(self):
        text, images = _prompt()
        plan = plan_video_references(
            "multi_reference", model="seedance-2.0", first_frame="https://cdn/frame.png", reference_images=images,
            intent=VideoGenerationIntent(identity_consistency_required=True),
        )
        self.assertEqual(plan.reference_images[0], "https://cdn/frame.png")
        sent = renumber_reference_mentions(text, images, plan)
        self.assertTrue(sent.startswith("参考图1是本镜首帧画面"))
        self.assertIn("林夏（参考图2）", sent)
        self.assertIn("周教授（参考图3）", sent)
        self.assertIn("地下实验室（参考图4）", sent)
        self.assertIn("参考图2仅锁定数字演员设定集「林夏」", sent)
        self.assertIn("参考图4仅锁定拍摄场地「地下实验室」", sent)
        for number, url in enumerate(plan.reference_images, start=1):
            if url == "https://cdn/zhou.png":
                self.assertIn(f"周教授（参考图{number}）", sent)

    def test_an_image_the_request_does_not_carry_is_no_longer_cited(self):
        text, images = _prompt()
        plan = VideoReferencePlan(mode="multi_reference", reference_images=["https://cdn/frame.png", "https://cdn/linxia.png"])
        sent = renumber_reference_mentions(text, images, plan)
        self.assertIn("林夏（参考图2）", sent)
        self.assertNotIn("周教授（参考图", sent)
        self.assertIn("看向周教授", sent)
        self.assertNotIn("「周教授」", sent, "the lock note for an image that is not sent is dropped")
        self.assertNotIn("参考图3", sent)

    def test_first_frame_modes_send_no_identity_images_so_none_is_cited(self):
        text, images = _prompt()
        plan = VideoReferencePlan(mode="first_last_frame", first_frame="https://cdn/a.png", last_frame="https://cdn/b.png")
        sent = renumber_reference_mentions(text, images, plan)
        self.assertNotIn("参考图", sent)
        self.assertIn("林夏在地下实验室里看向周教授", sent)

    def test_numbers_are_mapped_in_one_pass_without_chaining(self):
        text = "甲（参考图1）、乙（参考图2）"
        plan = VideoReferencePlan(mode="multi_reference", reference_images=["https://cdn/b.png", "https://cdn/a.png"])
        sent = renumber_reference_mentions(text, ["https://cdn/a.png", "https://cdn/b.png"], plan)
        self.assertEqual(sent, "甲（参考图2）、乙（参考图1）")


STUDY = {
    "id": "s-1", "kind": "scene", "name": "地下实验室", "description": "冷白顶灯，左侧铁门，右侧观察窗", "metadata": {},
    "image_url": "data:main",
    "views": {"scene_45": "data:45", "scene_depth": "data:depth", "scene_detail": "data:detail"},
}


def _still(binding: dict) -> str:
    contract = ShotMotionContract.from_panel(_panel(1))
    return compile_panel_still(contract, references=binding["references"], assets=binding["assets"]).prompt


class SceneBindingTests(unittest.TestCase):
    def _binding(self, layout: str = ""):
        task = {"task_id": "t-1", "assets": {"3_characters": [{"name": "林夏", "desc": "调查记者"}]}}
        context = compile_scene_context(
            task, {"scene_id": "E1S01", "content": "林夏在地下实验室里翻找档案。", "characters": ["林夏"]}, [STUDY],
        )
        return panel_context(context, {"desc": "林夏翻找档案", "characters": ["林夏"]}, layout=layout)

    def test_the_scene_reference_states_the_layout_and_never_lends_its_people(self):
        binding = self._binding("铁门在画面左侧、观察窗在画面右侧")
        main = binding["references"][0]
        self.assertEqual((main["image_url"], main["layout"]), ("data:main", "铁门在画面左侧、观察窗在画面右侧"))
        self.assertIn(
            "场景图只提供空间结构、陈设与材质（铁门在画面左侧、观察窗在画面右侧），不提供光线、天色和人物，光线以本格为准",
            _still(binding),
        )
        _, notes = merge_video_references(SHEETS[:1], binding["references"])
        self.assertIn("参考图1仅锁定数字演员设定集「林夏」的脸型、发型、体型与服装，不采用图中背景、版式与其他人物，不是额外剧情或额外人物", notes)
        self.assertIn("参考图2仅锁定拍摄场地「地下实验室」的空间布局，光线与天色以本场为准、不照搬此图（铁门在画面左侧、观察窗在画面右侧）", notes)
        # Without a plan the line still binds the space, just without the sides.
        self.assertIn("场景图只提供空间结构、陈设与材质，不提供光线、天色和人物", _still(self._binding()))

    def test_the_extra_views_come_last_each_with_its_purpose_and_none_takes_the_name(self):
        binding = self._binding("铁门在画面左侧")
        self.assertEqual([item.get("view", "") for item in binding["references"]], ["", "scene_45", "scene_depth", "scene_detail"])
        for line in ("图2 「地下实验室」场景图（45°斜角）", "图2 用于走位与转身时的透视",
                     "图3 用于纵深调度：走廊、门洞与前后景", "图4 用于特写与插入镜头的陈设材质"):
            self.assertIn(line, _still(binding))
        entries = video_reference_entries(SHEETS[:1], binding["references"])
        self.assertEqual([name for _, name, _ in entries], ["林夏", "地下实验室", "", "", ""])
        numbers = {name: number for number, (_, name, _) in enumerate(entries, start=1) if name}
        self.assertEqual(numbers, {"林夏": 1, "地下实验室": 2}, "@[地下实验室] points at the main view")

        images, notes = merge_video_references(SHEETS[:1], binding["references"])
        plan = VideoReferencePlan(mode="multi_reference", reference_images=["https://cdn/frame.png", *images[:3]])
        sent = renumber_reference_mentions(notes, images, plan)
        self.assertIn("参考图3仅锁定拍摄场地「地下实验室」的空间布局，光线与天色以本场为准、不照搬此图（铁门在画面左侧）", sent)
        self.assertIn("参考图4仅锁定拍摄场地「地下实验室」的45°斜角", sent)
        self.assertNotIn("纵深视角", sent, "a view the request does not carry loses its whole line")
        self.assertNotIn("关键细节", sent)

    def test_the_views_never_push_out_the_cast_or_the_props(self):
        props = [{"kind": "prop", "name": f"档案{i}", "image_url": f"data:p{i}"} for i in range(7)]
        task = {"task_id": "t-1", "assets": {"2_breakdown": {"production_assets": {}}}}
        context = compile_scene_context(task, {"scene_id": "E1S01", "content": "地下实验室里的档案" + "".join(p["name"] for p in props)}, [STUDY, *props])
        references = panel_context(context, {"desc": "镜头扫过" + "".join(p["name"] for p in props), "characters": []})["references"]
        self.assertEqual(len(references), 9)
        self.assertEqual([item.get("view", "") for item in references][-1], "scene_45")
        self.assertEqual(sum(1 for item in references if item["kind"] == "prop"), 7)


if __name__ == "__main__":
    unittest.main()
