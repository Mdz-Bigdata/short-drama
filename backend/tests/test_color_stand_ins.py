"""真人审核拦截时：分镜帧里的人换成彩色影子当站位参考，长相只认定妆照，提示词压短。"""

import unittest
from unittest.mock import patch

from app.core import color_stand_ins as stand_ins
from app.core import video_failures
from app.service.drama_service import DramaService
from tests.test_stage_five_failures import ARK_SENSITIVE, FRAME, StageFiveFailureRecordTests, _task

ROSTER = [
    ("沈砚", "男性，青色长衫", "男主角"),
    ("林晚", "女性，月白襦裙", "女主角"),
    ("赵恒", "男性，黑袍", "反派"),
    ("老周", "男性，粗布短打", "配角"),
]
GENDERS = {"沈砚": "male", "林晚": "female", "赵恒": "male", "老周": "male"}
CLOTHING = {"沈砚": "青色长衫", "林晚": "月白襦裙", "赵恒": "黑袍", "老周": "粗布短打"}


class PaletteTests(unittest.TestCase):
    def test_white_is_the_male_lead_blue_the_female_lead_yellow_the_villain(self):
        colors = stand_ins.palette(ROSTER, GENDERS)
        self.assertEqual(colors["沈砚"], ("白色", "男主角"))
        self.assertEqual(colors["林晚"], ("蓝色", "女主角"))
        self.assertEqual(colors["赵恒"], ("黄色", "反派"))
        self.assertEqual(colors["老周"], ("红色", "角色"))

    def test_a_cast_that_only_says_lead_is_split_by_gender(self):
        roster = [("林晚", "", "主角"), ("沈砚", "", "主角")]
        colors = stand_ins.palette(roster, {"林晚": "female", "沈砚": "male"})
        self.assertEqual(colors["沈砚"][0], "白色")
        self.assertEqual(colors["林晚"][0], "蓝色")

    def test_a_character_keeps_one_colour_in_every_shot(self):
        alone = stand_ins.figures([ROSTER[3]], ROSTER, GENDERS, CLOTHING)
        together = stand_ins.figures([ROSTER[0], ROSTER[3]], ROSTER, GENDERS, CLOTHING)
        self.assertEqual(alone[0].color, together[1].color)

    def test_crowds_turn_grey_when_the_villain_already_wears_yellow(self):
        with_villain = stand_ins.figures([ROSTER[0], ROSTER[2]], ROSTER, GENDERS, CLOTHING)
        self.assertEqual(stand_ins.crowd_color(with_villain), "灰色")
        self.assertEqual(stand_ins.crowd_color(stand_ins.figures([ROSTER[0]], ROSTER, GENDERS, CLOTHING)), "黄色")

    def test_crowds_are_read_from_the_description_or_an_uncast_name(self):
        names = [name for name, _desc, _role in ROSTER]
        self.assertTrue(stand_ins.has_crowd("围观的百姓让开一条路", ["沈砚"], names))
        self.assertTrue(stand_ins.has_crowd("沈砚推门", ["沈砚", "狱卒甲"], names))
        self.assertFalse(stand_ins.has_crowd("沈砚推门", ["沈砚"], names))


class ClothingTests(unittest.TestCase):
    def test_clothing_is_the_first_garment_in_the_card_not_its_age_or_scars(self):
        card = ("男配角/提灯老奴；男性，视觉年龄60–68；右手小指自第二指节远端缺失；灰白短束并系土褐布巾；"
                "土褐粗麻短褐，肘部与膝部有补丁；外系深褐围裙")
        self.assertEqual(stand_ins.clothing_from_description(card), "土褐粗麻短褐")
        self.assertEqual(stand_ins.clothing_from_description("男性，视觉年龄26–30"), "")


class PromptTests(unittest.TestCase):
    def setUp(self):
        self.figures = stand_ins.figures([ROSTER[0], ROSTER[1]], ROSTER, GENDERS, CLOTHING)

    def test_each_shadow_is_named_with_gender_and_clothing(self):
        legend = stand_ins.legend(self.figures, crowd=True)
        self.assertIn("白色影子是男主角沈砚（男，青色长衫）", legend)
        self.assertIn("蓝色影子是女主角林晚（女，月白襦裙）", legend)
        self.assertIn("其余黄色影子是群演", legend)

    def test_the_repaint_keeps_the_staging_and_removes_every_real_person(self):
        prompt = stand_ins.repaint_prompt(self.figures)
        for kept in ("站位", "姿势", "朝向", "构图"):
            self.assertIn(kept, prompt)
        self.assertIn("不出现真人", prompt)
        self.assertIn("白色影子是男主角沈砚", prompt)

    def test_frames_come_first_then_one_face_each_and_the_set_drops_at_the_limit(self):
        refs = stand_ins.references(["/a.png", "/b.png"], {"沈砚": "/shen.png", "林晚": "/lin.png"}, "/set.png", limit=4)
        self.assertEqual(refs.images, ["/a.png", "/b.png", "/shen.png", "/lin.png"])
        self.assertEqual(refs.face_numbers, {"沈砚": 3, "林晚": 4})
        self.assertIsNone(refs.scene_number)

    def test_the_clip_prompt_is_short_and_points_faces_at_the_look_photos(self):
        refs = stand_ins.references(["/a.png"], {"沈砚": "/shen.png", "林晚": "/lin.png"}, "/set.png")
        prompt = stand_ins.clip_prompt(
            self.figures, refs, action="沈砚推门而入，林晚回头。" * 20, dialogue="沈砚：你果然在这里。",
        )
        self.assertTrue(prompt.startswith("参考图1是站位参考"))
        self.assertIn("沈砚的长相只认参考图2的定妆照", prompt)
        self.assertIn("林晚的长相只认参考图3的定妆照", prompt)
        self.assertIn("参考图4只给场地", prompt)
        self.assertIn("台词：沈砚：你果然在这里", prompt)
        self.assertIn("不出现彩色影子", prompt)
        self.assertLess(len(prompt), 420, prompt)
        # 改号只认「（参考图N）」与「参考图N仅锁定……」两种写法；影子提示词两种都不用，号不会被改走。
        self.assertNotIn("（参考图", prompt)
        self.assertNotIn("仅锁定", prompt)


class StandInHintTests(unittest.TestCase):
    def test_a_refusal_that_survives_the_shadows_points_at_the_look_photo(self):
        entry = video_failures.build(
            scene_id="E1S09", shot_uids=[1], message=ARK_SENSITIVE, frames=["/p.png"], inputs=[],
            retried_without_frames=True, retried_with_stand_ins=True,
        )
        hint = video_failures.hint(entry)
        self.assertIn("彩色影子", hint)
        self.assertIn("定妆照", hint)
        self.assertIn("ARK_AUTHORIZED_FACE_ASSETS", hint)


class StageFiveStandInTests(unittest.TestCase):
    """一张被判疑似真人的分镜帧：重画成彩色影子，带定妆照重发，出片。"""

    setUp = StageFiveFailureRecordTests.setUp

    def _cast_task(self) -> dict:
        task = _task("shot")
        task["config"]["video_model"] = "seedance2.5"
        task["assets"]["3_characters"] = [{"name": "沈砚", "role": "男主角", "desc": "男性，青色长衫"}]
        task["assets"]["3_sheets"] = {"沈砚": "https://cdn/sheet.png"}
        return task

    def _run(self, task, *, refuse_shadows: bool = False) -> dict:
        """供应商拒收带 E1S09 分镜帧的请求(Ark 疑似真人)；``refuse_shadows`` 时影子重发也拒。"""
        self.videos: list[dict] = []
        self.images: list[dict] = []
        last = {"reason": ""}

        def generate_video(model, image_url, prompt, *args, **kwargs):
            refs = [image_url or "", *(kwargs.get("ref_images") or [])]
            self.videos.append({"first": image_url, "refs": refs[1:], "prompt": prompt})
            shadows = any("shadow" in str(url) for url in refs)
            if any("E1S09" in str(url) for url in refs) or (refuse_shadows and shadows):
                last["reason"] = ARK_SENSITIVE
                return None
            last["reason"] = ""
            return f"https://cdn/{abs(hash(tuple(refs))) % 10000}.mp4"

        def generate_image(model, prompt, ref_images=None, **kwargs):
            self.images.append({"prompt": prompt, "refs": list(ref_images or [])})
            return f"https://cdn/shadow-{len(self.images)}.png", {}

        self.repo.save_task(task["task_id"], task)
        with patch.object(self.service.gateway, "generate_video", side_effect=generate_video), \
             patch.object(self.service.gateway, "last_video_failure", side_effect=lambda: last["reason"]), \
             patch.object(self.service.gateway, "generate_image", side_effect=generate_image), \
             patch.object(self.service.gateway, "video_family_ready", return_value=True), \
             patch.object(self.service.gateway, "video_family_modes", return_value=None), \
             patch("app.service.drama_service.media_compositor.synthesize_preferred_dialogue_track", return_value=(None, None)), \
             patch("app.service.drama_service.media_compositor.attach_audio_to_clip", side_effect=lambda url, *a, **k: url), \
             patch.object(DramaService, "run_real_consistency_check", lambda _self, *a, **k: "OK"), \
             patch.dict("os.environ", {"GENERATION_CONCURRENCY_VIDEO": "1"}):
            try:
                self.service._execute_stage_blocking(task["task_id"], 5, _claimed_task=task)
            except RuntimeError:
                if not refuse_shadows:
                    raise
        return self.repo.get_task(task["task_id"])

    def test_the_refused_board_renders_from_coloured_shadows_and_the_look_photo(self):
        stored = self._run(self._cast_task())

        shadow_calls = [call for call in self.images if "影子" in call["prompt"]]
        self.assertTrue(shadow_calls, "the refused board was repainted")
        self.assertEqual(shadow_calls[0]["refs"], [FRAME.format(1)])
        self.assertIn("白色影子是男主角沈砚（男，青色长衫）", shadow_calls[0]["prompt"])

        retry = [call for call in self.videos if call["prompt"].startswith("参考图1是站位参考")]
        self.assertTrue(retry, "the clip was resent with the stand-in prompt")
        self.assertIsNone(retry[0]["first"], "shadows are a staging reference, never the opening frame")
        self.assertFalse(any("/frames/" in url for url in retry[0]["refs"]), "no storyboard frame goes out again")
        self.assertEqual(retry[0]["refs"][0], "https://cdn/shadow-1.png")
        self.assertIn("https://cdn/sheet.png", retry[0]["refs"])
        self.assertIn("沈砚的长相只认参考图2的定妆照", retry[0]["prompt"])

        clips = {(clip.get("scene_id"), clip.get("shot_id")): clip for clip in stored["assets"]["5"]}
        fallback = clips[("E1S09", 1)]["moderation_fallback"]
        self.assertEqual(fallback["dropped"], "storyboard_frames")
        self.assertIn("白色影子是男主角沈砚", fallback["color_stand_ins"]["legend"])
        self.assertEqual(stored["assets"].get(video_failures.FAILURES_KEY) or {}, {})
        self.assertIsNone(clips[("E1S01", 1)].get("moderation_fallback"), "a board that was never refused keeps its frames")

    def test_when_the_shadows_are_refused_too_the_frameless_retry_still_runs(self):
        stored = self._run(self._cast_task(), refuse_shadows=True)
        prompts = [call["prompt"] for call in self.videos]
        shadow_index = next(i for i, text in enumerate(prompts) if text.startswith("参考图1是站位参考"))
        self.assertGreater(len(prompts), shadow_index + 1, "the frame-less retry follows the refused shadow retry")
        clips = {(clip.get("scene_id"), clip.get("shot_id")): clip for clip in stored["assets"]["5"]}
        self.assertTrue(clips[("E1S09", 1)].get("video_url"), "the frame-less retry rescued the board")


if __name__ == "__main__":
    unittest.main()
