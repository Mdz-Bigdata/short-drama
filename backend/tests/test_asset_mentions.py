import unittest

from app.core import style_packs
from app.core.asset_mentions import mark_mentions, parse_mentions, resolve_mentions
from app.core.video_prompt_engine import ShotPromptInput, compile_shot_prompt, format_dialogue


class AssetMentionTests(unittest.TestCase):
    def test_names_are_marked_once_and_longest_first(self):
        text = mark_mentions("姜照坐在姜照工位前，@[罗荧]回头，罗荧不语。", ["姜照", "姜照工位", "罗荧"])
        self.assertEqual(text, "@[姜照]坐在@[姜照工位]前，@[罗荧]回头，@[罗荧]不语。")
        self.assertEqual(parse_mentions(text), ["姜照", "姜照工位", "罗荧"])

    def test_resolution_names_the_reference_image_and_drops_unknown_marks(self):
        text = "@[姜照]推开@[地府客服中心大厅]的门，@[路人]让开。"
        self.assertEqual(
            resolve_mentions(text, {"姜照": 1, "地府客服中心大厅": 3}),
            "姜照（参考图1）推开地府客服中心大厅（参考图3）的门，路人让开。",
        )

    def test_dialogue_lines_carry_the_speaker_and_the_delivery_note(self):
        self.assertEqual(
            format_dialogue("姜照（平静）：您说的是那套别墅吗？\n张建国：小姜？\n（画外音）喂？", ["姜照", "张建国"]),
            "@[姜照]（平静）{您说的是那套别墅吗？} @[张建国]{小姜？} {（画外音）喂？}",
        )


class AnchoredShotPromptTests(unittest.TestCase):
    def _shot(self, **overrides):
        values = dict(
            shot_index=3, duration_seconds=8, shot_size="中景转近景", camera_movement="固定机位，缓慢推近",
            subject_action="姜照敲击键盘，张建国在电话那头沉默", scene="阳间墓园售后工位",
            blocking="姜照居左下，张建国居右上", start_state="姜照盯着屏幕", end_state="手机滑落",
            characters=["姜照", "张建国"], dialogue="姜照（平静）：您说的是那套别墅吗？",
            cast_refs=["姜照", "张建国"], scene_refs=["阳间墓园售后工位"],
            composition="对角线构图：姜照居画面左下方，张建国居右上方",
        )
        values.update(overrides)
        return ShotPromptInput(**values)

    def test_the_prompt_opens_with_the_cast_and_scene_anchors(self):
        text = compile_shot_prompt(style_packs.FILM_35MM, self._shot(), model="seedance2.5").text
        self.assertIn("【人物锚点·锁脸】@[姜照]、@[张建国]。", text)
        self.assertIn("【场景锚点·锁场景】@[阳间墓园售后工位]。", text)
        self.assertLess(text.index("【人物锚点·锁脸】"), text.index("【结构声明】"))
        self.assertIn("景别：中景转近景；运镜：固定机位，缓慢推近", text)
        self.assertIn("构图：对角线构图：@[姜照]居画面左下方，@[张建国]居右上方", text)
        self.assertIn("@[姜照]（平静）{您说的是那套别墅吗？}", text)
        # 风格锁、铁律与负面词不标记
        self.assertNotIn("@[", text[text.index("【关键约束】"):])

    def test_a_shot_without_references_has_no_anchor_lines(self):
        text = compile_shot_prompt(
            style_packs.FILM_35MM, self._shot(cast_refs=(), scene_refs=()), model="seedance2.5",
        ).text
        self.assertNotIn("【人物锚点", text)
        self.assertNotIn("【场景锚点", text)
        # 正文里不标没有参考图的名字；台词说话人照样标出(发送前会解析回名字本身)。
        self.assertNotIn("@[阳间墓园售后工位]", text)
        self.assertIn("画面：姜照敲击键盘", text)
        self.assertIn("@[姜照]（平静）{", text)

    def test_anchor_lines_are_never_cut_by_a_tight_budget(self):
        compiled = compile_shot_prompt(
            style_packs.FILM_35MM, self._shot(subject_action="姜照盯着屏幕" * 40), model="jimeng",
        )
        self.assertIn("【人物锚点·锁脸】", compiled.text)
        self.assertNotIn("anchor_cast", compiled.pressure.dropped)


if __name__ == "__main__":
    unittest.main()
