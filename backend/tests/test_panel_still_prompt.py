import unittest

from app.core.panel_still_prompt import compile_panel_still, medium_line, palette_line, previous_ending
from app.core.shot_motion_contract import ShotMotionContract, assert_prompt_pair_consistent, compile_motion_prompt
from app.core.storyboard_scene_context import compile_scene_context, panel_context
from app.core import style_packs
from app.core.model_gateway import ModelGateway
from tests.test_production_contracts import _panel
from tests.test_storyboard_concurrency import generate_test_board


def _contract(**changes):
    return ShotMotionContract.from_panel(_panel(2)).model_copy(update={
        "characters": ["沈砚", "林晚"], "props": ["玉牌"], "effects": ["本格无额外特效"],
        "subject_action": "沈砚右手攥紧玉牌，抬眼看向林晚", "expression": "眉心收紧，转为冷笑", "dialogue": "",
        "start_state": "上一镜结束时的人物姿态、朝向与道具归属原样保留（硬切）", "end_state": "沈砚松开玉牌，手垂在身侧",
        "lighting": "本场时段天气：雨夜，内景；主光：烛火自画右下方；人物脸部保持自然层次", **changes,
    })


_REFERENCES = [
    {"kind": "actor", "name": "沈砚"}, {"kind": "actor", "name": "林晚"},
    {"kind": "scene", "name": "宗祠", "layout": "门在画面左侧"}, {"kind": "prop", "name": "玉牌"},
]
_ASSETS = [
    {"kind": "actor", "name": "沈砚", "description": "圆脸，高束马尾，黑发，青布长衫"},
    {"kind": "actor", "name": "林晚", "description": "杏眼，月白褙子"},
    {"kind": "effect", "name": "烛焰", "description": "橙色微颤"},
]


def _prompt(contract=None, **kwargs):
    kwargs.setdefault("references", _REFERENCES)
    kwargs.setdefault("assets", _ASSETS)
    return compile_panel_still(contract or _contract(), **kwargs).prompt


class TemplateTests(unittest.TestCase):
    def test_three_sections_in_the_order_of_the_template(self):
        prompt = _prompt(medium="真实电影质感", atmosphere="古装权谋调性", palette="烛火暖光#E8B06A")
        for earlier, later in (
            ("【落笔】", "参考图："), ("参考图：", "锚续："), ("锚续：", "生成一格分镜示例图"), ("生成一格分镜示例图", "调度："),
            ("调度：", "时段与光线："), ("时段与光线：", "表演："), ("表演：", "表情定格："), ("表情定格：", "发型："), ("发型：", "口型："),
            ("口型：", "持有物与接触点："), ("持有物与接触点：", "同场戏跨镜头一致："), ("同场戏跨镜头一致：", "【调色】"),
            ("【调色】", "介质与渲染标准：真实电影质感"), ("介质与渲染标准", "【收边】"), ("【收边】", "物理优先："),
            ("物理优先：", "画幅 9:16，二K 交付档"), ("画幅 9:16", "本格结束状态六锁："), ("六锁：", "本拍排除："), ("本拍排除：", "一格只演一个"),
        ):
            self.assertLess(prompt.index(earlier), prompt.index(later), f"{earlier} 应在 {later} 之前")
        self.assertIn("不是宫格拼版，不是海报，不是资产图，不是概念图。", prompt)
        self.assertIn("禁止宫格、拼贴、分屏、边框与编号", prompt)
        for lock in ("身份 沈砚、林晚", "服装 ", "道具 玉牌", "朝向 ", "光位 主光：烛火自画右下方", "色板 烛火暖光#E8B06A"):
            self.assertIn(lock, prompt)

    def test_it_shares_the_fingerprint_of_the_motion_prompt(self):
        contract = _contract()
        assert_prompt_pair_consistent(compile_panel_still(contract), compile_motion_prompt(contract))


class ReferenceTests(unittest.TestCase):
    def test_picture_numbers_follow_the_order_sent_to_the_model(self):
        prompt = _prompt()
        self.assertIn("参考图：图1 「沈砚」定妆照、图2 「林晚」定妆照、图3 「宗祠」场景图、图4 「玉牌」道具图。", prompt)
        self.assertIn("服装以图1 定妆照为准（青布长衫）", prompt)
        self.assertIn("门在画面左侧", prompt)

    def test_a_costume_picture_outranks_the_look_photo(self):
        prompt = _prompt(references=[*_REFERENCES, {"kind": "costume", "name": "林晚囚服"}])
        self.assertIn("「林晚」穿图5 的「林晚囚服」", prompt)
        self.assertNotIn("服装以图2 定妆照为准", prompt)

    def test_an_asset_without_a_picture_keeps_its_written_description(self):
        self.assertIn("「烛焰」没有参考图，按设定：橙色微颤", _prompt())

    def test_the_written_layout_of_a_scene_stays_even_with_a_picture(self):
        prompt = _prompt(assets=[{"kind": "scene", "name": "宗祠", "description": "批准布局：供桌居北"}])
        self.assertIn("「宗祠」设定：批准布局：供桌居北", prompt)

    def test_the_place_and_a_triggered_effect_are_named_even_without_any_library(self):
        prompt = _prompt(_contract(scene="宗祠正堂", effects=["烛焰微颤"]), references=[], assets=[])
        self.assertIn("调度：地点宗祠正堂；", prompt)
        self.assertIn("特效：烛焰微颤。", prompt)
        self.assertNotIn("特效：", _prompt())

    def test_two_people_are_declared_different_and_one_person_is_not(self):
        self.assertIn("沈砚、林晚是不同的角色", _prompt())
        self.assertNotIn("是不同的角色", _prompt(_contract(characters=["沈砚"])))

    def test_no_picture_says_so(self):
        self.assertIn("参考图：无", _prompt(references=[], assets=[]))

    def test_an_end_frame_counts_the_first_frame_as_picture_one(self):
        prompt = _prompt(references=[{"kind": "first_frame"}, {"kind": "actor", "name": "沈砚"}], frame_state="end")
        self.assertIn("参考图：图1 本格首帧、图2 「沈砚」定妆照。", prompt)
        self.assertIn("服装以图2 定妆照为准", prompt)


class OneVisibleActionTests(unittest.TestCase):
    MERGED = "沈砚推开祠堂的门；随后林晚从供桌后抬头；随后沈砚放下玉牌"

    def test_a_merged_panel_draws_only_its_first_beat_and_bans_the_later_ones(self):
        prompt = _prompt(_contract(subject_action=self.MERGED))
        self.assertIn("沈砚推开祠堂的门。", prompt)
        self.assertIn("不提前呈现：林晚从供桌后抬头", prompt)
        self.assertIn("不提前呈现：沈砚放下玉牌", prompt)
        self.assertIn("画面中最多2个人物", prompt)

    def test_an_end_frame_draws_the_last_beat(self):
        prompt = _prompt(_contract(subject_action=self.MERGED), frame_state="end")
        self.assertIn("沈砚放下玉牌。", prompt)
        self.assertIn("沈砚松开玉牌，手垂在身侧", prompt)
        self.assertNotIn("不提前呈现", prompt)

    def test_a_four_step_action_uses_its_own_pose(self):
        action = "起始姿态：沈砚背靠门板，重心在左脚\n主动作：右手拔刀\n身体联动：肩膀下沉，视线锁定前方\n结束姿态：刀尖指地"
        start, end = _prompt(_contract(subject_action=action)), _prompt(_contract(subject_action=action), frame_state="end")
        self.assertIn("右手拔刀。沈砚背靠门板，重心在左脚。", start)
        self.assertIn("表演：肩膀下沉，视线锁定前方", start)
        self.assertIn("右手拔刀。刀尖指地。", end)

    def test_only_one_expression_phase_is_kept(self):
        self.assertIn("表情定格：眉心收紧。", _prompt())
        self.assertIn("表情定格：冷笑。", _prompt(frame_state="end"))

    def test_the_placeholder_expression_is_not_sent_as_if_it_were_one(self):
        prompt = _prompt(_contract(expression="与本镜触发事件对应的可观察微表情与呼吸变化"))
        self.assertIn("表情定格：只取这一拍正在发生的一个表情阶段", prompt)


class HandoffTests(unittest.TestCase):
    def test_the_previous_ending_is_written_out_because_panels_are_drawn_side_by_side(self):
        prompt = _prompt(previous_end="沈砚按住桌沿")
        self.assertIn("承接上一格的结束状态", prompt)
        self.assertIn("上一格结束状态：沈砚按住桌沿。", prompt)
        self.assertNotIn("原样保留（硬切）", prompt)

    def test_the_first_panel_has_nothing_to_catch(self):
        prompt = _prompt(_contract(shot_id=1, continuity_in="建立空间与人物关系"), previous_end="别的场次")
        self.assertIn("本场第一格", prompt)
        self.assertNotIn("承接上一格", prompt)
        self.assertNotIn("别的场次", prompt)

    def test_a_stock_end_state_falls_back_to_the_previous_action(self):
        self.assertEqual(previous_ending("人物姿态、视线与道具停在下一镜可以直接承接的状态", "沈砚落座；随后沈砚抬手按住桌沿"), "沈砚抬手按住桌沿")
        self.assertEqual(previous_ending("沈砚右手按桌沿，上身前倾", "沈砚落座"), "沈砚右手按桌沿，上身前倾")


class LineTests(unittest.TestCase):
    def test_mouth_follows_who_speaks(self):
        self.assertIn("口型：闭口，不说话。", _prompt())
        spoken = _prompt(_contract(dialogue="沈砚：你早就知道。"))
        self.assertIn("口型：「沈砚」是说话的人；说话的人这句刚说完、嘴自然合上；听的人闭着嘴在听（或正要开口）；不画张嘴吐字的一瞬。", spoken)
        alone = _prompt(_contract(characters=["沈砚"], dialogue="沈砚：你早就知道。"))
        self.assertIn("口型：「沈砚」是说话的人；说话的人这句刚说完、嘴自然合上；不画张嘴吐字的一瞬。", alone)
        self.assertIn("口型：画内人物闭口", _prompt(_contract(dialogue="旁白：那一夜没有人睡。")))
        self.assertIn("口型：画内人物闭口", _prompt(_contract(dialogue="画外声音：开门。")))

    def test_the_words_of_the_line_stay_out_of_the_picture(self):
        self.assertNotIn("你早就知道", _prompt(_contract(dialogue="沈砚：你早就知道。")))

    def test_an_empty_shot_has_no_acting_lines(self):
        prompt = _prompt(_contract(characters=["空镜（无人物）"], dialogue=""), references=[], assets=[])
        for label in ("表演：", "表情定格：", "发型：", "口型："):
            self.assertNotIn(label, prompt)
        self.assertIn("身份 空镜，无人物", prompt)
        self.assertIn("空镜，不生成面孔", prompt)

    def test_a_crowd_cannot_be_counted(self):
        self.assertNotIn("个人物", _prompt(_contract(characters=["沈砚", "人群"])).split("本拍排除")[1].split("\n")[0])

    def test_contact_quotes_the_clause_that_touches_something(self):
        self.assertIn("持有物与接触点：沈砚右手攥紧玉牌。", _prompt())
        self.assertIn("玉牌的位置与归属沿用上一格，不换手", _prompt(_contract(subject_action="沈砚抬头望月")))
        self.assertIn("不额外添加手持物", _prompt(_contract(subject_action="沈砚抬头望月", props=["本格无额外道具"])))
        self.assertIn("持有物与接触点：沈砚把公文包放在桌角。", _prompt(_contract(subject_action="沈砚把公文包放在桌角", props=["本格无额外道具"])))

    def test_three_lights_are_written_and_an_empty_shot_needs_no_rim(self):
        prompt = _prompt()
        self.assertIn("主光（key）烛火自画右下方", prompt)
        self.assertIn("补光（fill）", prompt)
        self.assertIn("轮廓光（rim）", prompt)
        self.assertNotIn("轮廓光", _prompt(_contract(characters=["空镜（无人物）"]), references=[], assets=[]))

    def test_people_of_the_scene_who_are_not_in_this_panel_are_excluded(self):
        prompt = _prompt(absent=["周叔", "沈砚"])
        self.assertIn("不出现周叔", prompt)
        self.assertNotIn("不出现沈砚", prompt)

    def test_nothing_is_invented_when_the_table_has_no_light_or_palette(self):
        prompt = _prompt(_contract(lighting="继承场景圣经的主光方向、色温、时间和天气，人物脸部保持自然层次"))
        self.assertIn("主光（key）沿用本场建立镜", prompt)
        self.assertIn("色板 沿用本场建立镜", prompt)


class StyleTests(unittest.TestCase):
    def test_the_medium_is_the_style_lock_of_the_project(self):
        pack = style_packs.get_pack("film_35mm")
        self.assertIn(pack.style_caption, medium_line(pack, "真人电影写实"))
        self.assertIn("#E8B06A", palette_line(pack))
        self.assertEqual(palette_line(style_packs.get_pack("cinematic_realism")), "")


class FaceTests(unittest.TestCase):
    def test_panels_no_longer_ask_to_hide_the_face_but_keep_the_other_bans(self):
        prompts = []

        def draw(_model, prompt, **_kwargs):
            prompts.append(prompt)
            return f"https://image.test/{len(prompts)}.png", "seedance"

        generate_test_board(draw)
        self.assertTrue(prompts)
        for prompt in prompts:
            for banned in ("不展示清晰", "优先人物背影", "强逆光剪影", "正面真人脸", "正脸特写"):
                self.assertNotIn(banned, prompt)
            for kept in ("真实名人", "严禁任何非写实风格", "换脸"):
                self.assertIn(kept, prompt)

    def test_an_animated_pack_drops_the_ban_on_its_own_medium(self):
        pack = next(item for item in style_packs.list_packs() if item.medium != "live_action")
        line = style_packs.identity_negative(pack, ModelGateway.PANEL_IDENTITY_NEGATIVE)
        self.assertIn("真实名人", line)
        self.assertNotIn("动画", line)
        self.assertTrue(line.endswith(")"))


class SkeletonSentenceTests(unittest.TestCase):
    """对照《系统实际下发提示词骨架》补齐的固定句(app/data/prompt/panel_still.json)。"""

    def test_each_person_is_the_one_in_their_own_pictures(self):
        self.assertIn("每个角色的定妆照是该角色本人；沈砚、林晚是不同的角色，脸和服装都不互相借用。", _prompt())
        costumed = _prompt(references=[*_REFERENCES, {"kind": "costume", "name": "林晚囚服"}])
        self.assertIn("每个角色的定妆照与戏服图是该角色本人；沈砚、林晚是不同的角色", costumed)
        self.assertIn("每个角色的定妆照是该角色本人。", _prompt(_contract(characters=["沈砚"])))
        self.assertNotIn("该角色本人", _prompt(references=[], assets=_ASSETS))

    def test_assets_without_a_picture_are_named_before_they_are_described(self):
        prompt = _prompt(assets=[*_ASSETS, {"kind": "prop", "name": "铜铃", "description": "掌心大，铃舌缺一角"}])
        self.assertIn("以下资产没有参考图，按文字绘制，不要因为没有图就省略：烛焰、铜铃。「烛焰」没有参考图，按设定：橙色微颤；「铜铃」没有参考图", prompt)
        pictured = _prompt(assets=[{"kind": "actor", "name": "沈砚", "description": "圆脸"}])
        self.assertNotIn("以下资产没有参考图", pictured)

    def test_a_prop_with_its_own_picture_is_drawn_from_it(self):
        prompt = _prompt()
        self.assertIn("道具（形制照母版）：「玉牌」照图4（道具母版）画，改位置不改形制。", prompt)
        self.assertLess(prompt.index("时段与光线："), prompt.index("道具（形制照母版）："))
        self.assertLess(prompt.index("道具（形制照母版）："), prompt.index("表演："))
        self.assertNotIn("形制照母版", _prompt(references=_REFERENCES[:3]))

    def test_the_technique_baseline_quotes_the_table_and_invents_nothing(self):
        prompt = _prompt()
        contract = _contract()
        self.assertIn(f"技法基准：焦段 {contract.lens_mm}mm；光圈 {contract.aperture}；光位 烛火自画右下方。", prompt)
        self.assertLess(prompt.index("【调色】"), prompt.index("技法基准："))
        self.assertLess(prompt.index("技法基准："), prompt.index("【收边】"))
        written = _prompt(_contract(lighting="主光：烛火自画右下方；光比 1:4；色温 3200K"))
        self.assertIn("光比 1:4；色温 3200K；光位 烛火自画右下方。", written)
        for invented in ("光比", "色温 "):
            self.assertNotIn(invented, prompt.split("技法基准：")[1].split("\n")[0])

    def test_the_six_locks_say_what_may_only_grow(self):
        prompt = _prompt()
        self.assertIn("身份 沈砚、林晚，同一张脸同一发型同一体型；", prompt)
        self.assertIn("，破损浸润凌乱只增不减；道具 玉牌，磨损消耗只增不减；", prompt)
        bare = _prompt(_contract(eyeline="", props=["本格无额外道具"]), references=[], assets=[])
        self.assertIn("服装 承接定妆照与上一格，破损浸润凌乱只增不减；道具 无；朝向 承接上一格的身体朝向与视线；", bare)
        first = _prompt(_contract(eyeline="", shot_id=1))
        self.assertIn("朝向 以本格调度为准；", first)

    def test_light_and_palette_locks_carry_over_when_the_table_gives_none(self):
        plain = "继承场景圣经的主光方向、色温、时间和天气"
        later = _prompt(_contract(lighting=plain, shot_id=3))
        self.assertIn("光位 沿用本场建立镜，承接上一格的主光方向与色温；色板 沿用本场建立镜，承接参考图与上一格的主色次色点缀色。", later)
        first = _prompt(_contract(lighting=plain, shot_id=1))
        self.assertIn("光位 沿用本场建立镜的主光方向与色温；色板 沿用本场建立镜与参考图的主色次色点缀色。", first)
        self.assertNotIn("上一格的主光", first)


class FallbackProviderTests(unittest.TestCase):
    def test_the_short_form_for_other_providers_still_carries_the_action(self):
        long_setup = [{"kind": "actor", "name": f"角色{index}"} for index in range(1, 8)]
        sent = ModelGateway._sanitize_prompt_for_agnes(_prompt(references=long_setup, medium="真实电影质感"))
        self.assertLessEqual(len(sent), 600)
        self.assertIn("沈砚右手攥紧玉牌，抬眼看向林晚", sent)
        self.assertNotIn("参考图：", sent)
        self.assertNotIn("定妆照只提供", sent)

    def test_other_prompts_are_cut_as_before(self):
        self.assertEqual(ModelGateway._sanitize_prompt_for_agnes("雨夜长街，林夏回头"), "雨夜长街，林夏回头")


class PanelContextTests(unittest.TestCase):
    def test_a_panel_hands_over_the_text_of_its_assets_in_reference_order(self):
        task = {"task_id": "t", "assets": {}, "config": {}}
        scene = {"scene_id": "E1S01", "content": "沈砚在宗祠拿起玉牌", "characters": ["沈砚"], "location": "宗祠"}
        elements = [
            {"id": "1", "kind": "actor", "name": "沈砚", "description": "高束马尾", "metadata": {}, "image_url": "data:a"},
            {"id": "2", "kind": "prop", "name": "玉牌", "description": "青白玉", "metadata": {}, "image_url": "data:b"},
        ]
        context = compile_scene_context(task, scene, elements)
        binding = panel_context(context, {"desc": "沈砚拿起玉牌", "characters": ["沈砚"]})
        self.assertEqual([item["name"] for item in binding["references"]][:1], ["沈砚"])
        self.assertIn({"kind": "prop", "name": "玉牌", "description": "青白玉"}, binding["assets"])


if __name__ == "__main__":
    unittest.main()
