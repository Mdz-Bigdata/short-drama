import unittest

from app.core.face_card import (
    audit_face_card,
    card_negatives,
    fit_face_text_to_framing,
    framing_for_shot_size,
    parse_face_card,
    render_face_card,
)
from app.core.script_prompt_pipeline import ScriptPromptPipeline
from app.core.storyboard_director import StoryboardDirectorCompiler
from app.core.storyboard_quality import build_actor_sheet_prompt
from app.schema.script_prompts import ScriptPromptCompileRequest
from tests.test_storyboard_director import _request as director_request
from app.schema.storyboard_director import DirectorCharacter


EAST_ASIAN_DNA = (
    "28岁东亚女性，气质清冷；瓜子脸，下颌线柔和，浅眼窝；内双，低鼻根，圆钝鼻尖，左眼下泪痣；"
    "暖黄调半哑光皮肤，轻微肤色不均，眼下细纹；黑色低马尾；窄肩，四肢纤细；米白风衣；不要过度磨皮"
)


class FaceCardParsingTests(unittest.TestCase):
    def test_free_text_lands_in_the_layer_it_describes(self):
        card = parse_face_card(EAST_ASIAN_DNA)

        self.assertEqual(card.identity, ["28岁东亚女性", "气质清冷"])
        self.assertEqual(card.bone, ["瓜子脸", "下颌线柔和", "浅眼窝"])
        self.assertEqual(card.features, ["内双", "低鼻根", "圆钝鼻尖", "左眼下泪痣"])
        # 「眼下细纹」是皮肤质感，不是五官；「眼镜」「风衣」是服装配饰，不是长相。
        self.assertIn("眼下细纹", card.skin)
        self.assertEqual(card.hair, ["黑色低马尾"])
        self.assertEqual(card.physique, ["窄肩", "四肢纤细"])
        self.assertEqual(card.other, ["米白风衣"])

    def test_negations_leave_the_positive_text(self):
        card = parse_face_card(EAST_ASIAN_DNA)

        self.assertEqual(card.negatives, ["过度磨皮"])
        self.assertNotIn("磨皮", render_face_card(card))
        # 「别致」不是否定词。
        self.assertEqual(parse_face_card("别致的发簪").negatives, [])

    def test_rendered_card_parses_back_to_the_same_card(self):
        card = parse_face_card(EAST_ASIAN_DNA)
        rendered = render_face_card(card)

        self.assertTrue(rendered.startswith("身份锚点：28岁东亚女性、气质清冷；骨相：瓜子脸"))
        self.assertEqual(render_face_card(parse_face_card(rendered)), rendered)
        # 上游自己带了层名也不会叠成「骨相：骨相：」。
        self.assertEqual(parse_face_card("骨相：骨相：瓜子脸").bone, ["瓜子脸"])

    def test_text_without_any_face_layer_is_left_alone(self):
        placeholder = "剧本未提供可绑定的角色外貌（需确认）"

        self.assertEqual(fit_face_text_to_framing(placeholder, "中景"), (placeholder, []))


class FaceCardAuditTests(unittest.TestCase):
    def codes(self, text):
        return [issue.code for issue in audit_face_card(parse_face_card(text))]

    def test_a_clean_single_system_card_passes(self):
        self.assertEqual(self.codes(EAST_ASIAN_DNA), [])

    def test_mixing_two_bone_systems_is_flagged(self):
        issues = audit_face_card(parse_face_card("东亚女性，深眼窝，高鼻根，内眦褶"))

        self.assertEqual([issue.code for issue in issues], ["mixed_bone_system"])
        self.assertIn("混血脸", issues[0].message)

    def test_longest_match_wins_so_no_epicanthal_fold_is_european(self):
        self.assertEqual(self.codes("北欧女性，深眼窝，高鼻根，无内眦褶"), [])

    def test_label_and_anchors_from_different_systems(self):
        self.assertEqual(self.codes("北欧女性，浅眼窝，低鼻根"), ["label_anchor_conflict"])

    def test_too_many_skin_texture_words(self):
        self.assertIn("skin_overload", self.codes("东亚女性，浅眼窝，皮肤有毛孔，绒毛，细纹，雀斑"))

    def test_vague_population_label(self):
        self.assertEqual(self.codes("亚洲女性，瓜子脸"), ["vague_population_label"])
        self.assertEqual(self.codes("East Asian woman, oval face"), [])

    def test_single_system_card_avoids_the_other_systems_anchors(self):
        self.assertEqual(
            card_negatives(parse_face_card(EAST_ASIAN_DNA)),
            ["过度磨皮", "深眼窝", "高鼻根", "强眉弓"],
        )
        self.assertEqual(
            card_negatives(parse_face_card("Northern European woman, deep-set eyes, high nasal root")),
            ["面中平缓", "内眦褶"],
        )
        # 混用两套时不替人选边。
        self.assertEqual(card_negatives(parse_face_card("深眼窝，内眦褶")), [])


class FaceCardFramingTests(unittest.TestCase):
    def test_shot_sizes_map_to_what_the_frame_can_show(self):
        self.assertEqual(framing_for_shot_size("中近景"), "close")
        self.assertEqual(framing_for_shot_size("特写"), "close")
        self.assertEqual(framing_for_shot_size("全景"), "full")
        self.assertEqual(framing_for_shot_size("按事件信息量过渡"), "all")

    def test_close_shots_drop_physique_and_cap_skin_words(self):
        text, negatives = fit_face_text_to_framing(
            "东亚女性，浅眼窝，暖黄调皮肤，毛孔，绒毛，细纹，窄肩，四肢纤细", "近景"
        )

        self.assertNotIn("体态", text)
        self.assertNotIn("细纹", text)  # 第四个皮肤词被裁掉
        self.assertIn("毛孔", text)
        self.assertIn("深眼窝", negatives)

    def test_wide_shots_keep_physique_but_drop_skin_texture(self):
        text, _ = fit_face_text_to_framing(EAST_ASIAN_DNA, "全景")

        self.assertIn("体态：窄肩、四肢纤细", text)
        self.assertIn("皮肤：暖黄调半哑光皮肤", text)  # 肤色还看得见
        self.assertNotIn("眼下细纹", text)
        self.assertNotIn("轻微肤色不均", text)


class FaceCardWiringTests(unittest.TestCase):
    def test_actor_sheet_writes_the_layered_card_and_its_exclusions(self):
        prompt = build_actor_sheet_prompt("林夏", EAST_ASIAN_DNA, "写实电影", era_note="民国旗袍造型。")

        self.assertIn("人物资产卡：身份锚点：28岁东亚女性", prompt)
        self.assertIn("体态：窄肩、四肢纤细", prompt)
        self.assertIn("全身立绘与三视图严格按体态比例刻画", prompt)
        self.assertIn("民国旗袍造型。视觉风格：写实电影", prompt)
        self.assertIn("场景道具；禁止过度磨皮、深眼窝、高鼻根、强眉弓。", prompt)
        self.assertNotIn("不要过度磨皮", prompt)

    def test_still_prompt_crops_the_card_to_the_shot_size(self):
        request = director_request(
            characters=[DirectorCharacter(name="林夏", appearance=EAST_ASIAN_DNA, costume="米白风衣")],
        )
        request = request.model_copy(update={
            "shot_visual": request.shot_visual.model_copy(update={"shot_size": "中近景"}),
        })
        still = StoryboardDirectorCompiler().compile(request).still_prompts[0]

        self.assertIn("骨相：瓜子脸、下颌线柔和、浅眼窝", still.prompt)
        self.assertNotIn("四肢纤细", still.prompt.split("【连续性锁定】")[0])
        self.assertIn("深眼窝", still.exclusions)
        self.assertIn("过度磨皮", still.prompt.split("【排除】")[1])

    def test_script_pipeline_warns_about_mixed_bone_systems(self):
        result = ScriptPromptPipeline().compile(ScriptPromptCompileRequest(
            title="混骨相",
            script_text="场景1：咖啡厅内 - 夜晚\n林夏坐在窗边。\n【林夏】我知道了。\n",
            character_overrides={"林夏": "28岁东亚女性，深眼窝，高鼻根，内眦褶，黑色短发"},
            exports=["json"],
        ))

        codes = [issue.code for issue in result.consistency.issues]
        self.assertIn("face_card_mixed_bone_system", codes)
        self.assertTrue(result.characters[0].consistency_seed.startswith("[CHARACTER:林夏] 身份锚点："))
        # 面部锚点只锁看得见脸的层，体态层不进面部锁。
        still = result.director_plans[0].still_prompts[0].prompt
        self.assertIn("【连续性锁定】面部林夏：身份锚点：28岁东亚女性", still)


if __name__ == "__main__":
    unittest.main()
