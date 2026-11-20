# -*- coding: utf-8 -*-
"""第 3 阶段的四类资产——数字演员(含表演妆造)、拍摄场地(含置景)、拍摄道具(含车辆、商品)、特效(含特技)——
都带进分镜与视频提示词：每张参考图都有一句模型认得出的说明，号码指对图；物件带着真实大小；人坐进车里、坐上椅子不穿模。"""

import unittest

from app.core import breakdown_kinds, panel_still_prompt, tight_prompt, wuxia_vfx
from app.core.storyboard_scene_context import (
    OBJECT_KINDS, compile_scene_context, panel_context, real_size_note, reference_note,
)
from app.core.video_prompt_engine import body_contact_line
from app.core.video_references import VideoReferencePlan, renumber_reference_mentions

ACTOR = {"id": "a-1", "kind": "actor", "name": "沈砚", "description": "青衫书生", "metadata": {}, "image_url": "data:actor"}
SCENE = {"id": "s-1", "kind": "scene", "name": "雨夜长街", "description": "青石板路，两侧灯笼", "metadata": {}, "image_url": "data:scene"}
CART = {"id": "v-1", "kind": "vehicle", "name": "马车", "description": "双马拉的乌木马车，车厢挂青布帘", "metadata": {}, "image_url": "data:cart"}
TABLE = {"id": "d-1", "kind": "set_dressing", "name": "祠堂供桌", "description": "黑漆长条供桌", "metadata": {}, "image_url": "data:table"}
LEAP = {"id": "t-1", "kind": "stunt", "name": "屋顶飞跃", "description": "从檐角助跑起跳，落在对面屋脊上翻滚卸力", "metadata": {}, "image_url": "data:leap"}
CROWD = {"id": "e-1", "kind": "extra", "name": "街边摊贩", "description": "粗布短打的小贩", "metadata": {}, "image_url": "data:crowd"}
SWORD = {"id": "p-1", "kind": "prop", "name": "宝剑", "description": "", "metadata": {}, "image_url": "data:sword"}


def _task():
    return {"task_id": "aw-1", "config": {}, "assets": {"3_characters": [{"name": "沈砚", "desc": "书生"}]}}


def _context(content):
    return compile_scene_context(_task(), {"scene_id": "E1S01", "content": content, "characters": ["沈砚"]},
                                 [ACTOR, SCENE, CART, TABLE, LEAP, CROWD, SWORD])


class NoteRenumberTests(unittest.TestCase):
    def test_every_kind_of_note_follows_its_image_to_its_real_number(self):
        """首帧排在前面时，每类资产那句「参考图N仅锁定…」都改成图真正的号；没发出去的图连句子一起删。"""
        kinds = ["prop", "product", "effect", *breakdown_kinds.KINDS]
        images = [f"data:{kind}" for kind in kinds]
        notes = "；".join(reference_note(n, {"kind": kind, "name": f"名{kind}"}) for n, kind in enumerate(kinds, 1))
        sent = ["data:frame", *images[:-1]]
        text = renumber_reference_mentions(notes, images, VideoReferencePlan(mode="multi_reference", reference_images=sent))
        for n, kind in enumerate(kinds[:-1], 1):
            self.assertIn(f"参考图{n + 1}仅锁定", text.split(f"「名{kind}」")[0][-30:], kind)
        self.assertNotIn(f"「名{kinds[-1]}」", text, "the note of an image that was not sent goes with it")


class BindingTests(unittest.TestCase):
    def test_vehicles_and_products_are_handled_objects_and_carry_their_size(self):
        shot = panel_context(_context("沈砚掀帘坐进马车，按着宝剑。"), {"desc": "沈砚掀帘坐进马车，手按宝剑", "characters": ["沈砚"]})
        self.assertEqual(shot["props"], ["宝剑", "马车"])
        cart = next(item for item in shot["references"] if item["kind"] == "vehicle")
        self.assertIn("真实尺寸约长350×宽150×高220厘米", cart["size"], "the cart from the everyday supplement table")
        # 两张表都查不到的，写第 3 阶段画设定图时按的最长边(描述里写的或按类别估的)。
        self.assertEqual(real_size_note("vehicle", "飞鸢", "竹骨绢面的大风鸢"), "，最长边约30厘米，和人物同框时按这个比例画")
        sword = next(item for item in shot["references"] if item["kind"] == "prop")
        self.assertIn("真实尺寸约长100", sword["size"], "the reference table wins when it knows the thing")
        self.assertIn(cart["size"], reference_note(3, cart))
        self.assertEqual(real_size_note("vehicle", "无名车"), "", "a bare name with no description has no size to tell")
        self.assertEqual(set(OBJECT_KINDS), {"prop", "product", "vehicle"})

    def test_named_assets_go_before_old_costume_boards_and_unnamed_extras_go_last(self):
        context = _context("沈砚从屋顶飞跃到马车上，祠堂供桌前街边摊贩在叫卖。")
        context["costumes"] = [{"kind": "costume", "name": f"旧戏服{n}", "image_url": f"data:costume{n}", "description": "", "owner": "沈砚"} for n in range(6)]
        shot = panel_context(context, {"desc": "沈砚屋顶飞跃，落在马车上", "characters": ["沈砚"]}, crowd={"街边摊贩"})
        kinds = [item["kind"] for item in shot["references"]]
        self.assertLessEqual(len(kinds), 9)
        for kind in ("vehicle", "stunt"):
            self.assertIn(kind, kinds, "a named vehicle or stunt is not pushed out by old costume boards")
        self.assertLess(kinds.index("stunt"), kinds.index("costume") if "costume" in kinds else 99)
        self.assertNotIn("extra", kinds[:-1] if "extra" in kinds else kinds, "an unnamed extra only takes a place left over")


class HeadNounTests(unittest.TestCase):
    def test_a_described_prop_name_is_found_by_its_head_noun(self):
        """拆解目录的道具名带修饰(「凹坑磨石」)，剧本只写「磨石」：按结尾的物件名词认；两件同名词的谁也不认。"""
        from app.core.storyboard_scene_context import head_noun, named_by_noun

        stone = {"kind": "prop", "name": "凹坑磨石"}
        lamp = {"kind": "prop", "name": "粗陶油灯"}
        self.assertEqual((head_noun(stone), head_noun(lamp), head_noun({"kind": "prop", "name": "磨石"})), ("磨石", "油灯", ""))
        text = "油灯一盏，把磨石照出一小块暖橙。"
        self.assertTrue(named_by_noun(stone, text, [stone, lamp]))
        self.assertTrue(named_by_noun(lamp, text, [stone, lamp]))
        twin = {"kind": "prop", "name": "旧磨石"}
        self.assertFalse(named_by_noun(stone, text, [stone, twin]), "two whetstones: neither is guessed")
        self.assertFalse(named_by_noun({"kind": "stunt", "name": "青光磨石"}, text, []), "a stunt is matched by its whole name only")
        context = compile_scene_context(_task(), {"scene_id": "E1S01", "content": text, "characters": ["沈砚"]}, [ACTOR, SCENE, {
            "id": "p-9", "kind": "prop", "name": "凹坑磨石", "description": "青灰长条磨石", "metadata": {}, "image_url": "data:stone",
        }])
        self.assertEqual([item["name"] for item in context["props"]], ["凹坑磨石"])


class NamePieceTests(unittest.TestCase):
    def test_compound_and_described_names_are_found_by_their_pieces(self):
        from app.core.storyboard_scene_context import name_pieces, named_by_noun

        bench = {"kind": "set_dressing", "name": "长木案与矮条凳"}
        basin = {"kind": "set_dressing", "name": "墙角接雨木盆"}
        self.assertTrue({"长木案", "矮条凳", "条凳"} <= name_pieces(bench))
        self.assertTrue(named_by_noun(basin, "屋角接雨木盆一滴滴响", [bench, basin]))
        self.assertTrue(named_by_noun(bench, "靠墙长木案刀痕密布", [bench, basin]))
        self.assertNotIn("的刀", name_pieces({"kind": "prop", "name": "未开刃的刀"}))
        glow = {"kind": "effect", "name": "剑自出鞘三寸微光"}
        self.assertFalse(named_by_noun(glow, "窗外透进一点微光", [glow]), "a plain light word does not call up the effect")
        self.assertTrue(named_by_noun({"kind": "effect", "name": "油灯爆灯花"}, "灯焰一缩，爆出灯花", []))
        self.assertEqual(name_pieces({"kind": "stunt", "name": "三娘举刀不落"}), frozenset(), "stunts are matched by their name only")

    def test_the_scenes_shots_count_when_choosing_its_objects(self):
        """剧本只写「屋角木盆」，分镜写到「接雨木盆」：这一场照样有这件置景，镜头才绑得上。"""
        basin = {"id": "d-2", "kind": "set_dressing", "name": "墙角接雨木盆", "description": "半人高的旧木盆", "metadata": {}, "image_url": "data:basin"}
        task = _task()
        scene = {"scene_id": "E1S01", "content": "沈砚推门进铺。", "characters": ["沈砚"]}
        self.assertEqual(compile_scene_context(task, scene, [ACTOR, SCENE, basin])["set_dressing"], [])
        task["assets"]["4"] = [{"scene_id": "E1S01", "shot_id": 1, "desc": "沈砚推门，屋角接雨木盆一滴滴响"}]
        context = compile_scene_context(task, scene, [ACTOR, SCENE, basin])
        self.assertEqual([item["name"] for item in context["set_dressing"]], ["墙角接雨木盆"])
        shot = panel_context(context, {"desc": "沈砚推门，屋角接雨木盆一滴滴响", "characters": ["沈砚"]})
        self.assertIn(("set_dressing", "墙角接雨木盆"), [(item["kind"], item["name"]) for item in shot["references"]])


class AliasTests(unittest.TestCase):
    def test_the_breakdown_asks_for_aliases_and_they_reach_the_shot(self):
        from app.api.drama_api import _alias_patch
        from app.core.production_asset_extractor import extract_production_assets
        from app.service.drama_service import DramaService

        contract = DramaService._breakdown_contract(10, "seedance2.0")
        for kind in ("props", "effects", "vehicles", "stunts", "set_dressing"):
            self.assertIn(f'"{kind}": [{{"name": ', contract)
        self.assertEqual(contract.count('"aliases": ['), 5)

        drip = {"name": "屋檐滴水成珠", "aliases": ["滴水", "屋檐滴水成珠", " "], "description": "檐口每隔两秒坠一颗水珠"}
        task = _task()
        task["assets"]["2_breakdown"] = {"production_assets": {"effects": [drip]}}
        self.assertEqual(extract_production_assets(task, "effect")[0]["aliases"], ["滴水"])
        context = compile_scene_context(task, {"scene_id": "E1S01", "content": "檐下滴水，沈砚抬头。", "characters": ["沈砚"]}, [ACTOR, SCENE])
        self.assertEqual([item["name"] for item in context["effects"]], ["屋檐滴水成珠"])
        self.assertEqual(_alias_patch({"aliases": ["滴水"]}, {"aliases": ["水珠"]}), {"aliases": ["水珠", "滴水"]})
        self.assertEqual(_alias_patch({"aliases": ["水珠"]}, {"aliases": ["水珠"]}), {})


class CompactTests(unittest.TestCase):
    def test_seedance_2_keeps_a_label_and_the_size_for_every_image(self):
        notes = "；".join([
            reference_note(1, {"kind": "actor", "name": "沈砚"}),
            reference_note(2, {"kind": "vehicle", "name": "马车", "size": "，最长边约350厘米，和人物同框时按这个比例画"}),
            reference_note(3, {"kind": "stunt", "name": "屋顶飞跃"}),
            reference_note(4, {"kind": "set_dressing", "name": "祠堂供桌"}),
            reference_note(5, {"kind": "product", "name": "静音吹风机", "size": "，真实尺寸约长25×宽8×高20厘米，和人物同框时按这个比例画"}),
        ])
        prompt = "\n".join(["【参考素材职责】", notes, "沈砚（参考图1）掀帘坐进马车。运镜：缓推。", "画面：雨夜长街，灯笼摇晃，" * 150])
        compacted, fit = tight_prompt.compact(prompt, "doubao-seedance-2-0-260128")
        self.assertIn("names", fit.steps)
        binding = compacted.split("\n")[0]
        for row in ("沈砚＝参考图1", "马车＝参考图2（外形、材质与颜色，最长边约350厘米）", "屋顶飞跃＝参考图3（动作姿态与接触点）",
                    "祠堂供桌＝参考图4", "静音吹风机＝参考图5（外形、材质与颜色，真实尺寸约长25×宽8×高20厘米）"):
            self.assertIn(row, binding)
        self.assertEqual(binding.count("参考图1"), 1, "an image already named in the body is not bound twice")
        self.assertIn("运镜：缓推。", compacted, "storyboard and camera text stays")


    def test_a_matched_set_image_is_bound_once_with_what_the_shot_uses(self):
        from app.core.storyboard_scene_context import _set_note

        notes = "；".join([
            reference_note(1, {"kind": "actor", "name": "沈砚"}),
            _set_note(2, {"set": ["长剑", "长剑剑鞘"], "used": ["长剑"]}, "，真实尺寸约长100×宽4×高2厘米，和人物同框时按这个比例画"),
        ])
        prompt = "\n".join(["【参考素材职责】", notes, "沈砚（参考图1）拔出长剑。", "画面：雨夜长街，" * 250])
        binding = tight_prompt.compact(prompt, "seedance2.0")[0].split("\n")[0]
        self.assertIn("长剑与长剑剑鞘＝参考图2（画在同一张配套图里，本镜只用长剑，真实尺寸约长100×宽4×高2厘米）", binding)
        # 以「参考图N是」开头整行留着时，绑定行不再重复写这张图。
        kept = "\n".join(["【参考素材职责】", "参考图3是导演台白模；" + notes, "沈砚（参考图1）拔出长剑。", "画面：雨夜长街，" * 250])
        self.assertEqual(tight_prompt.compact(kept, "seedance2.0")[0].count("长剑剑鞘"), 1)


class CompactSizeTests(unittest.TestCase):
    def test_a_prop_named_in_the_body_keeps_its_size_in_the_binding(self):
        notes = "；".join([
            reference_note(1, {"kind": "actor", "name": "沈砚"}),
            reference_note(2, {"kind": "prop", "name": "凹坑磨石", "size": "，真实尺寸约长20×宽6×高3厘米，和人物同框时按这个比例画"}),
        ])
        prompt = "\n".join([
            "沈砚（参考图1）＝身份服装锚", "凹坑磨石（参考图2）＝道具锚", "【参考素材职责】", notes,
            "沈砚（参考图1）把刀压在凹坑磨石（参考图2）上。", "画面：雨夜，" * 300,
        ])
        binding = tight_prompt.compact(prompt, "seedance2.0")[0].split("\n")[0]
        self.assertIn("凹坑磨石＝参考图2（形制、材质、磨损，真实尺寸约长20×宽6×高3厘米）", binding)


class StillPromptTests(unittest.TestCase):
    def test_the_storyboard_frame_names_object_masters_with_their_size(self):
        refs = [{"kind": "vehicle", "name": "马车", "image_url": "x", "size": "，最长边约350厘米，和人物同框时按这个比例画"},
                {"kind": "prop", "name": "宝剑", "image_url": "y"}]
        rows = panel_still_prompt._prop_masters(["宝剑", "马车", "笔记本电脑"], refs)
        self.assertIn("「马车」照图1（道具母版）画，改位置不改形制，最长边约350厘米", rows)
        self.assertIn("「宝剑」照图2（道具母版）画，改位置不改形制，真实尺寸约长100", rows)
        self.assertIn("「笔记本电脑」按实物大小画，真实尺寸约长35", rows)


class UnpicturedTests(unittest.TestCase):
    def test_an_asset_with_no_picture_and_no_description_is_still_named(self):
        text = panel_still_prompt._written_assets(
            [{"kind": "prop", "name": "宝剑"}],
            [{"kind": "vehicle", "name": "马车", "description": ""}, {"kind": "stunt", "name": "屋顶飞跃", "description": "檐角起跳"}],
        )
        self.assertIn("不要因为没有图就省略：马车、屋顶飞跃。", text)
        self.assertIn("「屋顶飞跃」没有参考图，按设定：檐角起跳", text)


class UnpicturedVideoTests(unittest.TestCase):
    def test_an_object_without_a_picture_is_written_from_its_description(self):
        from app.core.storyboard_scene_context import unpictured_lines

        lines = unpictured_lines({
            "references": [{"kind": "prop", "name": "宝剑"}],
            "assets": [
                {"kind": "prop", "name": "宝剑", "description": "青铜古剑"}, {"kind": "vehicle", "name": "马车", "description": "乌木车厢。青布帘"},
                {"kind": "set_dressing", "name": "供桌", "description": ""}, {"kind": "effect", "name": "剑气", "description": "青光"},
            ],
        })
        self.assertEqual(lines, ["「马车」没有参考图，按设定画：乌木车厢，青布帘"])


class LaterNoteTests(unittest.TestCase):
    def test_a_description_does_not_leak_what_happens_later(self):
        from app.core.storyboard_scene_context import looks_only, unpictured_lines

        hooks = "土墙上钉七个铁钩，挂着旧菜刀。空着的那个钩子在第2集末尾挂上七缺口钝刀。"
        self.assertEqual(looks_only(hooks), "土墙上钉七个铁钩，挂着旧菜刀。")
        lines = unpictured_lines({"references": [], "assets": [{"kind": "set_dressing", "name": "铁钩", "description": hooks}]})
        self.assertNotIn("钝刀", lines[0])
        self.assertNotIn("钝刀", panel_still_prompt._written_assets([], [{"kind": "set_dressing", "name": "铁钩", "description": hooks}]))


class BodyContactTests(unittest.TestCase):
    def test_sitting_in_a_cart_or_on_a_chair_is_written_as_contact(self):
        line = body_contact_line("沈砚掀帘坐进马车，林晚靠在廊柱上轻笑", ["马车", "廊柱"], ["沈砚", "林晚"])
        self.assertTrue(line.startswith("身体接触："))
        self.assertIn("沈砚在马车里面", line)
        self.assertIn("不穿出马车的外壁", line)
        self.assertIn("林晚靠在廊柱上", line)
        self.assertIn("人坐在太师椅的座面上", body_contact_line("坐在太师椅上喝茶", ["太师椅"]))
        self.assertEqual(body_contact_line("他看着马车远去", ["马车"]), "")
        self.assertEqual(body_contact_line("他坐在地上", ["马车"]), "", "only things the shot names")


class UncutPhysicsTests(unittest.TestCase):
    def test_contact_handoff_and_effects_survive_a_tight_budget(self):
        from app.core import prompt_budget, prompt_distiller

        sections = {
            "subject": "沈砚掀帘坐进马车，按着宝剑。" * 200, "environment": "雨夜长街，" * 50,
            "contact": "身体接触：沈砚在马车里面，不穿出马车的外壁。", "handoff": "递接路径：两人相距约一臂。", "effects": "剑气：青白色弧形剑光",
        }
        kept, report = prompt_budget.compress(sections, "kling-2.6")
        for key in ("contact", "handoff", "effects"):
            self.assertEqual(kept[key], sections[key], key)
            self.assertNotIn(key, report.dropped)
        self.assertIn("environment", report.dropped, "other optional sections still give way")
        for key in ("contact", "handoff"):
            self.assertNotIn(key, prompt_distiller.distillable_for("kling-2.6"), "not condensed either")


class EffectTextTests(unittest.TestCase):
    def test_the_stage_3_description_wins_over_the_breakdown(self):
        task = {"assets": {"2_breakdown": {"production_assets": {"effects": [{"name": "剑气", "description": "旧的拆解描述"}]}}}}
        self.assertIn("旧的拆解描述", wuxia_vfx.effect_lines(["剑气"], task)[0])
        lines = wuxia_vfx.effect_lines(["剑气", "屋顶飞跃"], task, described={"剑气": "青白色弧形剑光", "屋顶飞跃": "檐角起跳，落脊翻滚"})
        self.assertIn("青白色弧形剑光", lines[0])
        self.assertNotIn("旧的拆解描述", lines[0])
        self.assertIn("檐角起跳", lines[1])


if __name__ == "__main__":
    unittest.main()


class RegeneratedFrameTests(unittest.TestCase):
    """第 5 阶段要自己重画首帧时，和第 4 阶段一样带本镜绑到的资产参考(这里是场地图)，不只是角色设定集。"""

    def test_a_first_frame_drawn_in_stage_5_carries_the_shots_assets(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        from app.service import spatial_stage_service as spatial_stage
        from app.core.shot_motion_contract import ShotMotionContract
        from app.repository.task_repo import TaskRepository
        from app.service.drama_service import DramaService
        from tests.test_desk_layers import _panel, _stage_plan

        panel = _panel()
        contract = ShotMotionContract.from_panel(panel)
        shot = {
            "shot_id": 1, "scene_id": "E1S01", "size": "MS", "motion": "固定机位", "desc": panel.subject_action, "dialogue": "",
            "sound": panel.sound, "duration": "5", "characters": ["林夏", "陈默"], "props": ["钢笔"],
            "motion_contract": contract.model_dump(mode="json"), "contract_fingerprint": contract.contract_fingerprint,
        }
        task = {
            "task_id": "regen-frame", "owner_user_id": "u1", "current_stage": 4, "status": "running",
            "stage_progress": {"stage": 5, "status": "running", "calls": []},
            "workflow_control": {"run_id": "run-1", "active": True, "pause_requested": False},
            "config": {"video_model": "minimax-h3", "image_model": "seedream", "tts_model": "elevenlabs", "llm_model": "deepseek",
                       "title_suggestion": "离婚协议", "director_style": "realistic", "episode_count": 1, "video_granularity": "shot"},
            "assets": {
                "1": "方案", "2": "第1集 开场\n场景1：书房\n林夏：你早就知道了。\n陈默：那份合同，是你签的。", "3": "角色",
                "3_sheets": {"林夏": "/media/linxia.png", "陈默": "/media/chenmo.png"},
                "3_characters": [{"name": "林夏", "gender": "女", "desc": "28岁女性"}, {"name": "陈默", "gender": "男", "desc": "32岁男性"}],
                "4": [shot],
            },
            "logs": {}, "chat_history": [],
        }
        spatial_stage.save_plan(task, _stage_plan())
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        service = DramaService()
        service.repo = TaskRepository(str(Path(temp.name) / "tasks.json"))
        service.repo.save_task(task["task_id"], task)
        drawn: list = []

        def generate_image(model, prompt, *args, **kwargs):
            drawn.append((prompt, list(kwargs.get("ref_images") or [])))
            return "https://cdn/frame.png", {}

        plate = [{"kind": "scene", "id": "study", "name": "书房", "description": "旧书架与红木书桌", "image_url": "https://img.test/study.png"}]
        with patch.object(service.gateway, "generate_video", return_value="https://cdn/1.mp4"), \
             patch.object(service.gateway, "generate_image", side_effect=generate_image), \
             patch.object(service.gateway, "call_llm", return_value=""), \
             patch.object(service.gateway, "video_family_ready", return_value=True), \
             patch.object(service.gateway, "video_family_modes", return_value=None), \
             patch("app.service.drama_service.media_compositor.synthesize_preferred_dialogue_track", return_value=(None, None)), \
             patch("app.service.drama_service.media_compositor.attach_audio_to_clip", side_effect=lambda url, *a, **k: url), \
             patch("app.service.drama_service.load_storyboard_elements", return_value=plate), \
             patch.object(DramaService, "run_real_consistency_check", lambda _self, *a, **k: "OK"):
            service._execute_stage_blocking(task["task_id"], 5, _claimed_task=task)
        self.assertTrue(drawn, "stage 5 drew the missing first frame")
        prompt, refs = drawn[0]
        self.assertIn("https://img.test/study.png", refs, "the set plate goes to the image model too")
        self.assertIn("「书房」", prompt)
