# -*- coding: utf-8 -*-
"""换装与参考复刻：服装提取、换装、三个改图模板，和给视频节点用的参考复刻词。"""

import unittest

from app.core import canvas_tools, canvas_workflow, prompt_data, studio_canvas
from app.core.canvas_tools import CanvasToolError
from app.service import canvas_tool_ops


def _prompt(tool, text="", **params):
    return canvas_tools.image_prompt(canvas_tools.get_tool(tool), params, text)


class OutfitToolTests(unittest.TestCase):
    def test_the_two_outfit_tools_call_the_image_model_and_the_remake_wording_is_free(self):
        tools = {tool.id: tool for tool in canvas_tools.TOOLS}
        self.assertEqual((tools["outfit_extract"].engine, tools["outfit_extract"].images), ("image", 1))
        self.assertEqual((tools["outfit_swap"].engine, tools["outfit_swap"].images), ("image", 2))
        self.assertEqual((tools["reference_remake"].engine, tools["reference_remake"].output), ("local", "text"))

    def test_extraction_keeps_the_whole_outfit_and_leaves_out_the_wearer(self):
        prompt = _prompt("outfit_extract", "只要上衣和裙子")
        for words in ("整套服装、鞋、包和配饰", "不重新搭配", "没有真人、人台或衣架", "纯白背景", "只要上衣和裙子"):
            self.assertIn(words, prompt)
        self.assertTrue(prompt.endswith(prompt_data.text("canvas_tools", "module.no_text")))

    def test_the_swap_gives_each_picture_one_job_and_pins_the_pose_to_the_person(self):
        prompt = _prompt("outfit_swap")
        self.assertLess(prompt.index("图1管人"), prompt.index("图2只管整套服装"))
        for words in ("只换衣服", "姿势照图1", "不学图2里衣服摆放的姿势和宽度", "受光方向、影子和衣料的明暗接得上图1的环境"):
            self.assertIn(words, prompt)


class TemplateTests(unittest.TestCase):
    def test_the_empty_room_takes_the_people_and_their_shadows_and_keeps_the_light(self):
        prompt = _prompt("template_edit", template="empty_room")
        for words in ("所有的人和他们落在地面、墙面上的影子", "不留残影", "房间、家具、光线、构图和画面尺寸不变"):
            self.assertIn(words, prompt)

    def test_a_recolour_needs_the_colours_and_keeps_the_cut(self):
        with self.assertRaises(CanvasToolError):
            _prompt("template_edit", template="recolor_outfit")
        prompt = _prompt("template_edit", "午夜蓝上衣配铂金灰长裙", template="recolor_outfit")
        for words in ("午夜蓝上衣配铂金灰长裙", "款式、剪裁", "原来的颜色不留在任何一片上", "不多出说明之外的服装颜色"):
            self.assertIn(words, prompt)

    def test_adding_words_does_not_end_by_forbidding_words(self):
        with self.assertRaises(CanvasToolError):
            _prompt("template_edit", template="add_text")
        prompt = _prompt("template_edit", "毛衣胸前加黑色粗体「广告位招租」", template="add_text")
        self.assertIn("逐字写准", prompt)
        self.assertNotIn(prompt_data.text("canvas_tools", "module.no_text"), prompt)
        self.assertTrue(prompt.endswith(prompt_data.text("canvas_tools", "module.no_other_text")))


class RemakeTests(unittest.TestCase):
    def test_a_person_swap_keeps_everything_of_the_clip_but_the_person(self):
        text = canvas_tools.remake_prompt({}, "")
        for words in ("动作、走位、运镜", "只把视频里的人换成参考图1里的人", "转头和侧脸时仍是同一张脸"):
            self.assertIn(words, text)
        self.assertTrue(canvas_tools.remake_prompt({"mode": "swap"}, "写实风格").endswith("写实风格"))

    def test_camera_only_needs_the_new_content_and_bars_the_old(self):
        with self.assertRaises(CanvasToolError):
            canvas_tools.remake_prompt({"mode": "camera"}, "  ")
        text = canvas_tools.remake_prompt({"mode": "camera"}, "一艘飞船掠过环形山")
        self.assertIn("只学参考视频的运镜、镜头节奏、景别变化和构图", text)
        self.assertIn("原片里的人物、服装、场景和画面内容都不出现", text)
        self.assertTrue(text.endswith("一艘飞船掠过环形山"))

    def test_the_outfit_change_names_its_three_pictures_and_one_action(self):
        text = canvas_tools.remake_prompt({"mode": "outfit"}, "")
        self.assertLess(text.index("参考图1是换装前"), text.index("参考图2是换装后"))
        for words in ("参考图3是没有人的同一个房间", "不走位、不换机位", "5 到 8 秒"):
            self.assertIn(words, text)

    def test_an_unknown_way_is_refused(self):
        with self.assertRaises(CanvasToolError):
            canvas_tools.remake_prompt({"mode": "nope"}, "x")

    def test_running_it_calls_no_model(self):
        made = canvas_tool_ops.run_tool(
            canvas_tools.get_tool("reference_remake"), inputs=studio_canvas.Inputs(), params={"mode": "outfit"}, prompt="", model="local", tag="t",
            task={}, drama=None,
        )
        self.assertEqual(made, {"text": canvas_tools.remake_prompt({"mode": "outfit"}, "")})

    def test_the_workflow_planner_is_told_how_to_wire_them(self):
        rules = prompt_data.text("canvas_workflow", "module.rules")
        self.assertIn("人物底图和这一套的服装图按这个顺序连到 outfit_swap", rules)
        self.assertIn("reference_remake", rules)
        described = canvas_workflow.planning_prompt("给她换三套衣服")
        for label in ("服装提取", "换装", "参考复刻词"):
            self.assertIn(label, described)


if __name__ == "__main__":
    unittest.main()
