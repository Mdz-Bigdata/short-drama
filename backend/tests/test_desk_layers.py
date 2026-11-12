# -*- coding: utf-8 -*-
"""参考分层(导演台白模 / 场地图 / 起止关键帧各管一件事)与固定项一句。

带着有效的导演台白模(静帧或白模视频)时：白模只管空间结构、人物站位与家具位置，不管材质、颜色与光线；
每张场地图只取材质、色调、光影与年代感，没有一张是构图来源。没有白模时一字不变。
导演台上摆了布景时 Pa1 写一句「固定：…位置全程不变，人物不换位」，看得见的、点到名的布景在前，整句有字数上限。
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import prompt_data, slice_video, style_packs
from app.core.shot_motion_contract import ShotMotionContract
from app.core.spatial_stage import SceneBrief, ShotSpec, build_plan
from app.core.storyboard_scene_context import bind_scene_frames, desk_layers, merge_video_references
from app.core.video_prompt_engine import ShotPromptInput, compile_shot_prompt, fixed_items_line, fixed_set_pieces
from app.core.video_references import VideoReferencePlan, renumber_reference_mentions
from app.repository.task_repo import TaskRepository
from app.schema.production import StoryboardPanel
from app.service import director_desk_service as desk
from app.service import spatial_stage_service as spatial_stage
from app.service.drama_service import DramaService
from tests import test_storyboard_scene_context as scene_tests

CLIP = prompt_data.load("clip_prompt")
VIEWS = prompt_data.load("scene_views")
OPENING = "参考图1是开场画面，只决定开场构图、站位与光线；"
DESK_FIRST = "参考图1是导演台白模，只决定空间结构、人物站位与家具位置，材质、颜色与光线不照它；"
DESK_SECOND = "参考图2是导演台白模，只决定空间结构、人物站位与家具位置，材质、颜色与光线不照它；"
DESK_DUTY = "的材质、色调、光影与年代感，天色以本场为准，站位与家具位置以导演台白模为准"
DIALOGUE = {"characters": ["沈砚", "贺兰霆"], "size": "中景", "dialogue": "沈砚：刀磨好了。"}

# 改动之前的原文(没有导演台白模时必须一字不差)。
PAIR_NOTES_BEFORE = (
    "参考图1仅锁定数字演员设定集「沈砚」的脸型、发型、体型与服装，不采用图中背景、版式与其他人物，不是额外剧情或额外人物；"
    "参考图2仅锁定数字演员设定集「贺兰霆」的脸型、发型、体型与服装，不采用图中背景、版式与其他人物，不是额外剧情或额外人物；"
    "参考图3仅锁定拍摄场地「磨刀铺内」正面的空间布局，光线与天色以本场为准、不照搬此图（磨刀石在画面左侧），"
    "是本镜唯一的场景构图来源：机位朝向、前景与背景按这张图，其他场地视角图的前景背景不混入本镜，图中人物不作参考，不是额外剧情或额外人物；"
    "参考图4仅锁定拍摄场地「磨刀铺内」反打（与正面相对）的空间布局，光线与天色以本场为准、不照搬此图，是反打方向（机位身后一侧），"
    "只核对那一侧的陈设，本镜不拍这一侧，正面与反打是同一场地、同一画风，左右按机位方向互换，图中人物不作参考，不是额外剧情或额外人物"
)
OPENED_BEFORE = (
    "参考图1是开场画面，只决定开场构图、站位与光线；【参考素材职责】\n"
    "参考图2仅锁定数字演员设定集「赵光义」的脸型、发型、体型与服装，不采用图中背景、版式与其他人物，不是额外剧情或额外人物；"
    "参考图3仅锁定拍摄场地「大殿」正面的空间布局，光线与天色以本场为准、不照搬此图，开场构图以开场画面为准，这张图只核对同一朝向的陈设，"
    "其他场地视角图的前景背景不混入本镜，图中人物不作参考，不是额外剧情或额外人物；"
    "参考图4仅锁定拍摄场地「大殿」的45°斜角，只核对陈设与材质，不决定本镜机位与构图，前景背景不带入本镜，图中人物不作参考，不是额外剧情或额外人物；"
    "参考图5仅锁定拍摄场地「大殿」的纵深视角，只核对陈设与材质，不决定本镜机位与构图，前景背景不带入本镜，图中人物不作参考，不是额外剧情或额外人物；"
    "参考图6仅锁定拍摄场地「大殿」的关键细节，只核对陈设与材质，不决定本镜机位与构图，前景背景不带入本镜，图中人物不作参考，不是额外剧情或额外人物。"
)


def _plan_of(images):
    return VideoReferencePlan(mode="multi_reference", provider_family="seedance", provider_status="x", reference_images=images)


class OpeningLineTests(unittest.TestCase):
    def setUp(self):
        references = scene_tests.SceneFrameTests._references()
        bind_scene_frames(references, {"size": "全景"}, empty_shot=False)
        self.images, notes = merge_video_references([], references)
        self.prompt = "【参考素材职责】\n" + notes + "。"

    def test_without_a_desk_still_the_opening_line_is_byte_identical(self):
        plan = _plan_of(["frame", *self.images])
        self.assertEqual(renumber_reference_mentions(self.prompt, self.images, plan), OPENED_BEFORE)
        self.assertEqual(renumber_reference_mentions(self.prompt, self.images, plan, desk_still=""), OPENED_BEFORE)
        self.assertEqual(CLIP["opening_picture"], OPENING)
        # 带着的白模静帧没发出去(首帧模式)：也不提它。
        first_frame = VideoReferencePlan(mode="first_frame", provider_family="seedance", provider_status="x", first_frame="frame")
        self.assertNotIn("导演台白模", renumber_reference_mentions(self.prompt, self.images, first_frame, desk_still="desk"))

    def test_a_desk_still_that_opens_says_it_only_decides_space_positions_and_furniture(self):
        text = renumber_reference_mentions(self.prompt, self.images, _plan_of(["desk", *self.images]), desk_still="desk")
        self.assertTrue(text.startswith(DESK_FIRST))
        self.assertNotIn("开场画面，只决定开场构图、站位与光线", text)
        self.assertEqual(text.count("导演台白模"), 1)

    def test_a_desk_still_after_the_storyboard_frame_is_named_by_its_own_number(self):
        text = renumber_reference_mentions(self.prompt, self.images, _plan_of(["frame", "desk", *self.images]), desk_still="desk")
        self.assertTrue(text.startswith(OPENING + DESK_SECOND))
        # 讲图本身的行以「参考图N是」开头：发前去重(tight_prompt)照留。
        self.assertTrue(CLIP["opening_desk"].startswith("参考图{n}是"))
        # 再跑一遍不重复加。
        again = renumber_reference_mentions(text, self.images, _plan_of(["frame", "desk", *self.images]), desk_still="desk")
        self.assertEqual(again.count("导演台白模"), 1)


class PlateDutyTests(unittest.TestCase):
    def _send(self, shot, desk_on):
        case = scene_tests.ShotReversePairTests()
        context, _ = case._context()
        shot = {"desc": "、".join(shot["characters"]) + "在铺里", **shot}
        from app.core.storyboard_scene_context import panel_context
        references = panel_context(context, shot, layout="磨刀石在画面左侧", desk=desk_on)["references"]
        return references, merge_video_references([], references)[1]

    def test_without_a_desk_capture_the_plate_lines_are_byte_identical(self):
        references, notes = self._send(DIALOGUE, desk_on=False)
        self.assertEqual(notes, PAIR_NOTES_BEFORE)
        self.assertFalse(any(ref.get("desk") for ref in references))

    def test_a_desk_capture_demotes_every_plate_to_look_only(self):
        references, notes = self._send(DIALOGUE, desk_on=True)
        self.assertTrue(all(ref.get("desk") for ref in references if ref["kind"] == "scene"))
        self.assertIn("参考图3仅锁定拍摄场地「磨刀铺内」正面" + DESK_DUTY + "（磨刀石在画面左侧）" + VIEWS["desk_composition"], notes)
        self.assertIn("参考图4仅锁定拍摄场地「磨刀铺内」反打（与正面相对）" + DESK_DUTY + VIEWS["reverse_space"], notes)
        # 发前去重(tight_prompt)按这个标记认出让了站位的场地图：每句都带着它。
        self.assertEqual(notes.count(VIEWS["desk_demoted_marker"]), 2)
        self.assertIn(VIEWS["desk_demoted_marker"], VIEWS["desk_scope"])
        # 正反打的写法还在，但没有一张是构图来源、也不再说空间布局。
        self.assertEqual(notes.count(VIEWS["pair_note"]), 1)
        self.assertNotIn("构图来源", notes)
        self.assertNotIn("空间布局", notes)
        # 演员那几句不动。
        self.assertTrue(notes.startswith(PAIR_NOTES_BEFORE.split("参考图3")[0]))

    def test_views_and_reverse_shots_are_demoted_too_and_the_sentences_stay_renumberable(self):
        references = scene_tests.SceneFrameTests._references()
        bind_scene_frames(references, {"size": "中景", "angle": "侧面过肩"}, empty_shot=False, desk=True)
        images, notes = merge_video_references([], references)
        self.assertIn("「大殿」45°斜角" + DESK_DUTY + VIEWS["desk_composition"], notes)
        self.assertNotIn("用于", notes)
        self.assertNotIn("构图来源", notes)
        references = scene_tests.SceneFrameTests._references()
        bind_scene_frames(references, {"angle": "反打"}, empty_shot=False, desk=True)
        self.assertIn(DESK_DUTY + VIEWS["reverse"], merge_video_references([], references)[1])
        # 整句改号、没发出去的整句删掉。
        prompt = "【参考素材职责】\n" + notes + "。"
        text = renumber_reference_mentions(prompt, images, _plan_of(["desk", *images[:2]]), desk_still="desk")
        self.assertEqual(text.count(DESK_DUTY), 1)
        self.assertNotIn("纵深视角", text)

    def test_a_clip_made_of_several_moments_is_relabelled_without_touching_the_moments(self):
        references = scene_tests.SceneFrameTests._references()
        bind_scene_frames(references, {"size": "全景"}, empty_shot=False, desk=True)
        plain = desk_layers(references, desk=False)
        self.assertFalse(any(ref.get("desk") for ref in plain))
        self.assertTrue(all(ref.get("desk") for ref in references if ref["kind"] == "scene"), "各瞬间自己的参考不动")
        self.assertFalse(any(ref.get("desk") for ref in desk_layers(references, desk=True) if ref["kind"] != "scene"))


def _stage_plan(desc="林夏放下钢笔"):
    return build_plan(SceneBrief(
        scene_id="E1S01", location="书房 / 夜 / 内景", text="林夏坐在书案后，陈默站在书案前。窗边一把扶手椅。",
        characters=["林夏", "陈默"], props=["钢笔"],
        shots=[ShotSpec(1, ["林夏", "陈默"], "", "中景", "平视", "固定", desc), ShotSpec(2, ["林夏"], "", "特写", "平视", "固定", "林夏垂眼")],
    ))


class FixedItemsTests(unittest.TestCase):
    def test_visible_or_named_set_pieces_come_first_and_held_props_are_left_out(self):
        plan = _stage_plan()
        front, rest = fixed_set_pieces(plan, [1])
        self.assertIn("书案", front)
        self.assertNotIn("钢笔", [*front, *rest], "搁在书案上的钢笔会被拿起来：不算固定项")
        # 特写里看不见的布景，文字点到名字就排前面。
        front, rest = fixed_set_pieces(plan, [2])
        self.assertEqual(front, [])
        front, rest = fixed_set_pieces(plan, [2], text="林夏走到窗前")
        self.assertEqual(front, ["窗"])
        self.assertIn("书案", rest)
        # 本镜要拿的道具不算。
        self.assertNotIn("书案", sum(fixed_set_pieces(plan, [1], handled=["书案"]), []))
        self.assertEqual(fixed_set_pieces(None, [1]), ([], []))

    def test_the_line_lists_only_as_many_names_as_fit(self):
        self.assertEqual(fixed_items_line(["书案", "窗", "扶手椅"]), "固定：书案、窗、扶手椅位置全程不变，人物不换位。")
        self.assertEqual(fixed_items_line(["书案"], people=False), "固定：书案位置全程不变。")
        self.assertEqual(fixed_items_line([]), "")
        many = [f"雕花博古架{i}" for i in range(20)]
        line = fixed_items_line(many)
        self.assertLessEqual(len(line), CLIP["fixed_items"]["max_chars"])
        self.assertTrue(line.startswith("固定：雕花博古架0、雕花博古架1"))
        self.assertNotIn("雕花博古架19", line)
        # 一个名字就超长也照样写这一个(长短限制不能把固定项整句抹掉)。
        self.assertIn("书" * 70, fixed_items_line(["书" * 70, "窗"]))

    def test_the_line_sits_in_pa1_once_also_in_fights_and_is_not_measured(self):
        base = dict(
            shot_index=1, duration_seconds=5, shot_size="MS", camera_movement="固定机位", subject_action="林夏放下钢笔",
            scene="书房", blocking="林夏坐在书案后", start_state="林夏坐在书案后", end_state="林夏坐定", characters=["林夏"],
        )
        plain = compile_shot_prompt(style_packs.FILM_35MM, ShotPromptInput(**base), model="seedance2.0")
        fixed = compile_shot_prompt(style_packs.FILM_35MM, ShotPromptInput(**base, fixed_items=["书案", "窗"]), model="seedance2.0")
        line = "固定：书案、窗位置全程不变，人物不换位。"
        self.assertNotIn("固定：", plain.text.split("Pa2")[0])
        self.assertEqual(fixed.text.count(line), 1)
        self.assertIn(line, fixed.text.split("Pa2")[0])
        self.assertLess(fixed.text.index(CLIP["one_change"]), fixed.text.index(line))
        self.assertEqual(fixed.pressure.length, plain.pressure.length, "每条重申的固定句，不计入正文预算")
        fight = compile_shot_prompt(style_packs.FILM_35MM, ShotPromptInput(**base, fixed_items=["书案"], situations=["fight"]), model="seedance2.0")
        self.assertIn("固定：书案位置全程不变", fight.text)
        self.assertEqual(plain.text, compile_shot_prompt(style_packs.FILM_35MM, ShotPromptInput(**base, fixed_items=[]), model="seedance2.0").text)

    def test_a_clip_of_several_moments_says_it_once(self):
        beat = slice_video.Beat(
            sections={"locks": "[空间锚]书房", "camera": "景别：MS；运镜：固定机位", "subject": "画面：林夏放下钢笔。", "end_state": "落幅：停住",
                      "fixed_items": "固定：书案位置全程不变，人物不换位。"},
            size="MS", motion="固定机位",
        )
        compiled = slice_video.compile_prompt([beat, beat, beat], model="seedance2.0", fixed_items=["书案", "窗"])
        self.assertEqual(compiled.text.count("固定："), 1)
        self.assertIn("固定：书案、窗位置全程不变，人物不换位。", compiled.text.split("【镜头1/3")[0])
        self.assertNotIn("固定：书案位置全程不变，人物不换位。", compiled.text, "各瞬间自己的那句不逐块写")
        fight = slice_video.compile_prompt([beat, beat], model="seedance2.0", fixed_items=["书案"], fight=True)
        self.assertEqual(fight.text.count("固定："), 1)
        self.assertNotIn("固定：", slice_video.compile_prompt([beat, beat], model="seedance2.0").text)


def _panel():
    return StoryboardPanel(
        index=1, characters=["林夏", "陈默"], shot_size="MS", camera_angle="平视", camera_movement="固定机位",
        camera_reason="稳住双人关系", lens_mm=50, aperture="T2.8", composition="双人中景，林夏画左、陈默画右",
        action_axis="摄影机在书案南侧，林夏在画左、陈默在画右", eyeline="林夏望向陈默", subject_action="林夏放下钢笔，抬眼看向陈默",
        expression="克制", scene="书房", props=["钢笔"], effects=["无"], dialogue="", sound="室内安静底噪",
        lighting="台灯暖光", edit_in="承接上一镜", edit_out="停在落幅", generation_mode="auto",
        blocking="林夏坐在书案后，陈默站在书案前约一米", start_state="林夏坐在书案后，陈默站在书案前",
        end_state="林夏直视陈默", continuity_out="林夏直视陈默",
    )


class StageFiveDeskTests(unittest.TestCase):
    """第 5 阶段整条走一遍(供应商全部替身)：白模静帧、白模视频、都没有、没有导演台方案。"""

    def _run(self, capture: str = "", *, stage_plan: bool = True) -> tuple[str, list]:
        panel = _panel()
        contract = ShotMotionContract.from_panel(panel, storyboard_image="/media/E1S01_1.png")
        shot = {
            "shot_id": 1, "scene_id": "E1S01", "size": "MS", "motion": "固定机位", "desc": panel.subject_action, "dialogue": "",
            "sound": panel.sound, "duration": "5", "image_url": "/media/E1S01_1.png", "characters": ["林夏", "陈默"], "props": ["钢笔"],
            "motion_contract": contract.model_dump(mode="json"), "contract_fingerprint": contract.contract_fingerprint,
        }
        task = {
            "task_id": "desk-layers", "owner_user_id": "u1", "current_stage": 4, "status": "running",
            "stage_progress": {"stage": 5, "status": "running", "calls": []},
            "workflow_control": {"run_id": "run-1", "active": True, "pause_requested": False},
            "config": {
                "video_model": "minimax-h3", "image_model": "seedream", "tts_model": "elevenlabs", "llm_model": "deepseek",
                "title_suggestion": "离婚协议", "director_style": "realistic", "shot_style": "cinematic", "episode_count": 1,
                "video_granularity": "shot",
            },
            "assets": {
                "1": "方案", "2": "第1集 开场\n场景1：书房\n林夏：你早就知道了。\n陈默：那份合同，是你签的。", "3": "角色",
                "3_sheets": {"林夏": "/media/linxia.png", "陈默": "/media/chenmo.png"},
                "3_characters": [{"name": "林夏", "gender": "女", "desc": "28岁女性"}, {"name": "陈默", "gender": "男", "desc": "32岁男性"}],
                "4": [shot],
            },
            "logs": {}, "chat_history": [],
        }
        if stage_plan:
            spatial_stage.save_plan(task, _stage_plan())
        if capture:
            url = f"/media/desk_{capture}.{'png' if capture == 'still' else 'mp4'}"
            desk._scene(task, "E1S01")["captures"].append({"id": "c1", "kind": capture, "shot_id": 1, "url": url, "stale": False})
            desk.apply_capture(task, "E1S01", "c1")
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        service = DramaService()
        service.repo = TaskRepository(str(Path(temp.name) / "tasks.json"))
        service.repo.save_task(task["task_id"], task)
        sent: list = []

        def generate_video(model, image_url, prompt, *args, **kwargs):
            sent.append((prompt, kwargs.get("ref_images") or []))
            return f"https://cdn/{len(sent)}.mp4"

        plate = [{"kind": "scene", "id": "study", "name": "书房", "description": "", "image_url": "https://img.test/study.png"}]
        with patch.object(service.gateway, "generate_video", side_effect=generate_video), \
             patch.object(service.gateway, "generate_image", return_value=("https://cdn/frame.png", {})), \
             patch.object(service.gateway, "call_llm", return_value=""), \
             patch.object(service.gateway, "video_family_ready", return_value=True), \
             patch.object(service.gateway, "video_family_modes", return_value=None), \
             patch("app.service.drama_service.media_compositor.synthesize_preferred_dialogue_track", return_value=(None, None)), \
             patch("app.service.drama_service.media_compositor.attach_audio_to_clip", side_effect=lambda url, *a, **k: url), \
             patch("app.service.drama_service.load_storyboard_elements", return_value=plate), \
             patch.object(DramaService, "run_real_consistency_check", lambda _self, *a, **k: "OK"):
            service._execute_stage_blocking(task["task_id"], 5, _claimed_task=task)
        self.assertEqual(len(sent), 1)
        return sent[0]

    def test_without_a_desk_capture_the_plate_still_locks_the_layout(self):
        prompt, images = self._run()
        self.assertTrue(prompt.startswith(OPENING + "Pa1"))
        self.assertIn("「书房」正面的空间布局", prompt)
        self.assertNotIn("导演台白模", prompt)
        self.assertIn("书房（参考图4）＝场景锚", prompt)
        self.assertNotIn("场景质感锚", prompt)
        self.assertIn(self._fixed(prompt), prompt.split("Pa2")[0])

    def test_a_desk_still_is_named_as_the_spatial_skeleton_and_the_plate_gives_only_the_look(self):
        prompt, images = self._run("still")
        self.assertEqual(images[:2], ["/media/E1S01_1.png", "/media/desk_still.png"])
        self.assertTrue(prompt.startswith(OPENING + DESK_SECOND))
        self.assertIn("「书房」正面" + DESK_DUTY, prompt)
        self.assertNotIn("「书房」正面的空间布局", prompt)
        self.assertNotIn("空间布局与环境动态", prompt, "场景锚点也不再说空间布局")
        self.assertIn("书房（参考图5）＝场景质感锚", prompt, "锚型定义也不让场景图管站位")
        self.assertIn("场景质感锚 材质 色调 光影", prompt)
        self.assertNotIn("场景锚 环境结构 陈设 材质", prompt)

    def test_a_blockout_clip_alone_demotes_the_plate_too(self):
        prompt, _ = self._run("clip")
        self.assertTrue(prompt.startswith(OPENING + "Pa1"))
        self.assertIn("「书房」正面" + DESK_DUTY, prompt)
        self.assertNotIn("空间布局", prompt)
        self.assertIn("书房（参考图4）＝场景质感锚", prompt)
        self.assertNotIn("环境结构 陈设", prompt)

    def test_the_fixed_items_line_comes_from_the_stage_plan_once_and_is_absent_without_one(self):
        prompt, _ = self._run()
        line = self._fixed(prompt)
        self.assertTrue(line.startswith("固定：书案"))
        self.assertLessEqual(len(line), CLIP["fixed_items"]["max_chars"])
        self.assertEqual(prompt.count(line), 1)
        prompt, _ = self._run(stage_plan=False)
        self.assertNotIn("位置全程不变，人物不换位", prompt)

    @staticmethod
    def _fixed(prompt: str) -> str:
        return next(line for line in prompt.splitlines() if line.startswith("固定：") and "位置全程不变" in line)


if __name__ == "__main__":
    unittest.main()
