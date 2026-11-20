# -*- coding: utf-8 -*-
"""配套画在一张图里的几样资产(「长剑」与「长剑剑鞘」)在第 5 阶段只发一次图，那句职责写成配套图。

出图时长的那条记 ``drawn_together``(画进去的短的名字)，短的那条记 ``drawn_with``(长的名字)，
两条各存一份同一张图(地址不同)。本镜两样都用到时只发一张；只用到一样时也说明图里还有什么、哪样不进画面。
"""

import unittest

from app.core.storyboard_scene_context import compile_scene_context, drawn_set, panel_context, reference_note
from app.core.video_references import VideoReferencePlan, renumber_reference_mentions

ACTOR = {"id": "a-1", "kind": "actor", "name": "沈砚", "description": "青衫书生", "metadata": {}, "image_url": "data:actor"}
SWORD = {"id": "p-1", "kind": "prop", "name": "长剑", "description": "", "metadata": {"drawn_with": "长剑剑鞘"}, "image_url": "data:sword-copy"}
SHEATH = {"id": "p-2", "kind": "prop", "name": "长剑剑鞘", "description": "", "metadata": {"drawn_together": ["长剑"]}, "image_url": "data:sword-set"}
CUP = {"id": "p-3", "kind": "prop", "name": "茶盏", "description": "", "metadata": {}, "image_url": "data:cup"}


def _panel(content):
    task = {"task_id": "ds-1", "config": {}, "assets": {"3_characters": [{"name": "沈砚", "desc": "书生"}]}}
    context = compile_scene_context(task, {"scene_id": "E1S01", "content": content, "characters": ["沈砚"]}, [ACTOR, SWORD, SHEATH, CUP])
    return panel_context(context, {"desc": content, "characters": ["沈砚"]})


def _objects(panel):
    return [reference for reference in panel["references"] if reference["kind"] == "prop"]


class DrawnSetTests(unittest.TestCase):
    def test_the_set_is_read_from_either_side(self):
        self.assertEqual(drawn_set(SHEATH), ["长剑剑鞘", "长剑"])
        self.assertEqual(drawn_set(SWORD), ["长剑剑鞘", "长剑"])
        self.assertEqual(drawn_set(CUP), [])

    def test_both_in_the_shot_send_one_picture(self):
        panel = _panel("沈砚拔出长剑，把长剑剑鞘丢在地上，碰倒茶盏。")
        objects = _objects(panel)
        self.assertEqual(len([item for item in objects if item.get("set")]), 1, "the two copies of the same picture go out once")
        together = next(item for item in objects if item.get("set"))
        self.assertEqual(sorted(together["used"]), ["长剑", "长剑剑鞘"])
        note = reference_note(3, together)
        self.assertTrue(note.startswith("参考图3是「长剑剑鞘」与「长剑」的配套图"), note)
        self.assertNotIn("本镜只用", note)
        self.assertNotIn("；", note)
        self.assertNotIn("。", note)
        self.assertIn("data:cup", [item["image_url"] for item in objects], "an unrelated prop still has its own picture")
        # 两样名字都还在本镜的物件清单里：持有、接触按名字认。
        self.assertIn("长剑", panel["props"])
        self.assertIn("长剑剑鞘", panel["props"])

    def test_one_in_the_shot_says_the_other_stays_out(self):
        panel = _panel("沈砚握着长剑。")
        together = next(item for item in _objects(panel) if item.get("set"))
        note = reference_note(2, together)
        self.assertIn("「长剑剑鞘」与「长剑」的配套图", note)
        self.assertIn("本镜只用其中的「长剑」，其余几样不进画面", note)

    def test_the_set_note_follows_its_picture_to_its_real_number(self):
        panel = _panel("沈砚拔出长剑，把长剑剑鞘丢在地上。")
        together = next(item for item in _objects(panel) if item.get("set"))
        images = [together["image_url"]]
        text = renumber_reference_mentions(reference_note(1, together), images, VideoReferencePlan(
            mode="multi_reference", reference_images=["data:frame", *images],
        ))
        self.assertIn("；参考图2是「长剑剑鞘」与「长剑」的配套图", text)


if __name__ == "__main__":
    unittest.main()
