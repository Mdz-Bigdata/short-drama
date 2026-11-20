"""样片与局部修：480p 样片、本地放大、从这里往后重做、区域修补。

真跑 ffmpeg(几秒的测试画面)，不调视频模型。
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.core import clip_fixes, media_compositor
from app.repository.task_repo import TaskRepository
from app.service.drama_service import DramaService

FFMPEG = shutil.which("ffmpeg")


def _clip(directory: str, name: str, *, seconds: float, size: str = "320x568", colour: str = "testsrc", audio: bool = True) -> str:
    command = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"{colour}=size={size}:rate=24:duration={seconds}"]
    if audio:
        command += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-shortest"]
    command += ["-pix_fmt", "yuv420p", os.path.join(directory, name)]
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return media_compositor.public_url(name)


class WordingTests(unittest.TestCase):
    def test_draft_mode_asks_for_480p_unless_the_shot_was_sent_back_for_hd(self):
        self.assertIsNone(clip_fixes.draft_resolution({}))
        self.assertEqual(clip_fixes.draft_resolution({"video_draft": True}), "480p")
        self.assertIsNone(clip_fixes.draft_resolution({"video_draft": True}, {"hd_retake": True}))

    def test_the_retake_prompt_starts_from_the_frame_and_names_the_fix(self):
        prompt = clip_fixes.retake_prompt("断水抬刀。", 4.5, "左手不要穿过刀身。")
        self.assertTrue(prompt.startswith("首帧是这一镜进行到第 4.5 秒时的画面"))
        self.assertIn("这一段要改掉的问题：左手不要穿过刀身。", prompt)
        self.assertTrue(prompt.endswith("断水抬刀。"))

    def test_the_repair_prompt_names_the_region_and_keeps_everything_else(self):
        prompt = clip_fixes.repair_prompt("去掉门口多出来的人", {"x": 0, "y": 0.6, "w": 0.4, "h": 0.4}, 2, 5)
        self.assertIn("只修改画面左下角约占画面四分之一的区域，第 2 秒到第 5 秒之间：去掉门口多出来的人", prompt)
        self.assertIn("修改区域以外的一切都不变", prompt)
        self.assertIn("画面正中", clip_fixes.region_words({"x": 0.3, "y": 0.3, "w": 0.4, "h": 0.4}))
        with self.assertRaises(ValueError):
            clip_fixes.repair_prompt("  ", {"x": 0, "y": 0, "w": 1, "h": 1})

    def test_an_expired_seedream_link_is_not_sent_as_a_character_reference(self):
        # 第 3 阶段的设定集是火山 TOS 的 24 小时签名链接：过期了供应商取不到，整条请求被拒。
        from app.service.drama_service import actor_identity_urls
        old = "https://ark.tos-cn-beijing.volces.com/a.jpeg?X-Tos-Date=20261106T095659Z&X-Tos-Expires=86400&X-Tos-Signature=x"
        fresh = old.replace("20261106", "20991106")
        urls = actor_identity_urls({"assets": {"3_sheets": {"谢九": old, "裘三娘": fresh}}})
        self.assertEqual(urls, {"裘三娘": fresh})

    def test_a_480p_h3_draft_names_its_aspect_ratio(self):
        # H3 在 480P 下的 ref2va 不认空比例(1000 aspect ratio "" is not supported)；768P 照旧由素材推。
        from app.core.providers.minimax_h3 import MiniMaxH3Client
        from app.schema.production import H3VideoRequest
        refs = ["https://cdn.example.com/a.png"]
        draft = MiniMaxH3Client._payload(H3VideoRequest(prompt="断水抬刀", reference_images=refs, resolution="480p"))
        full = MiniMaxH3Client._payload(H3VideoRequest(prompt="断水抬刀", reference_images=refs, resolution="768p"))
        self.assertEqual((draft["resolution"], draft.get("ratio")), ("480P", "9:16"))
        self.assertNotIn("ratio", full)

    def test_only_a_public_address_can_be_sent_as_a_reference_video(self):
        for url in ("http://localhost:8000/media/a.mp4", "http://127.0.0.1/media/a.mp4", "http://192.168.1.5/a.mp4", ""):
            self.assertFalse(clip_fixes.provider_can_fetch(url), url)
        self.assertTrue(clip_fixes.provider_can_fetch("https://cdn.example.com/a.mp4"))


@unittest.skipUnless(FFMPEG and shutil.which("ffprobe"), "needs ffmpeg")
class MediaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        media = patch.object(media_compositor, "MEDIA_DIR", self.temp.name)
        media.start()
        self.addCleanup(media.stop)

    def test_a_retake_keeps_the_start_and_the_spliced_clip_is_as_long_as_the_original(self):
        head = _clip(self.temp.name, "head.mp4", seconds=6)
        tail = _clip(self.temp.name, "tail.mp4", seconds=4, size="640x1136", colour="smptebars", audio=False)
        spliced = clip_fixes.splice(head, 2.5, tail, tag="t")
        facts = clip_fixes._probe(media_compositor.local_media_path(spliced))
        self.assertAlmostEqual(facts["duration"], 6, delta=0.25)
        self.assertEqual((facts["width"], facts["height"]), (320, 568), "the redone part is fitted to the original size")
        self.assertTrue(facts["audio"], "a tail with no sound gets silence, the seam keeps one audio track")
        self.assertTrue(clip_fixes.frame_at(head, 2.5).startswith("data:image/jpeg;base64,"))

    def test_upscaling_a_draft_brings_its_short_side_to_1080(self):
        draft = _clip(self.temp.name, "draft.mp4", seconds=2, size="272x480")
        upscaled = clip_fixes.upscale(draft, tag="hd")
        facts = clip_fixes._probe(media_compositor.local_media_path(upscaled))
        self.assertEqual(facts["width"], 1080)
        self.assertAlmostEqual(facts["duration"], 2, delta=0.1)


@unittest.skipUnless(FFMPEG and shutil.which("ffprobe"), "needs ffmpeg")
class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        media = patch.object(media_compositor, "MEDIA_DIR", self.temp.name)
        media.start()
        self.addCleanup(media.stop)
        self.url = _clip(self.temp.name, "shot.mp4", seconds=6)
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.repo.save_task("t", {
            "task_id": "t", "owner_user_id": "u", "status": "completed", "current_stage": 5,
            "config": {"video_model": "seedance2.0", "video_draft": True},
            "assets": {
                "4": [{"shot_id": 1, "scene_id": "E1S01", "desc": "断水抬刀"}],
                "5": [{"shot_id": 1, "scene_id": "E1S01", "shot_uid": 100101, "video_url": self.url, "candidates": [self.url],
                       "duration": 6, "draft_resolution": "480p", "seed": 7}],
            },
        })
        self.service = DramaService()
        self.service.repo = self.repo
        workspace = patch.object(self.service, "get_shot_visual_workspace", return_value={"ok": True})
        workspace.start()
        self.addCleanup(workspace.stop)

    def _clip(self) -> dict:
        return self.repo.get_task("t")["assets"]["5"][0]

    def test_hd_and_retake_requests_mark_the_shot_for_the_next_stage_5_run(self):
        self.service.regenerate_shot("t", 1, scene_id="E1S01", hd=True)
        self.assertTrue(self._clip()["hd_retake"])
        self.assertIn("样片转高清", self._clip()["stale_reason"])
        self.service.regenerate_shot("t", 1, scene_id="E1S01", retake_from=3.5, note="刀从左手穿过去了")
        self.assertEqual(self._clip()["retake"], {"from_seconds": 3.5, "note": "刀从左手穿过去了"})
        self.assertIn("保留前 3.5 秒", self._clip()["stale_reason"])

    def test_upscaling_keeps_the_draft_and_puts_the_bigger_clip_first(self):
        self.service.upscale_shot("t", 1, scene_id="E1S01")
        clip = self._clip()
        self.assertEqual(clip["draft_url"], self.url)
        self.assertTrue(clip["draft_upscaled"])
        self.assertNotEqual(clip["video_url"], self.url)
        self.assertEqual(clip["candidates"][0], clip["video_url"])

    def test_region_repair_refuses_a_clip_the_model_cannot_fetch(self):
        with self.assertRaisesRegex(ValueError, "PUBLIC_BASE_URL"):
            self.service.repair_shot("t", 1, box={"x": 0, "y": 0, "w": 0.5, "h": 0.5}, note="去掉多出来的人", scene_id="E1S01")
        self.assertNotIn("repair", self._clip())

    def test_region_repair_sends_the_clip_as_a_reference_video_and_swaps_in_the_result(self):
        fixed = _clip(self.temp.name, "fixed.mp4", seconds=6, colour="smptebars")
        self.service.gateway = MagicMock()
        self.service.gateway.generate_video.return_value = fixed
        with patch("app.core.clip_fixes.provider_can_fetch", return_value=True), \
                patch("app.service.drama_service.threading.Thread") as thread:
            self.service.repair_shot("t", 1, box={"x": 0, "y": 0.6, "w": 0.4, "h": 0.4}, note="去掉门口多出来的人", start=2, end=5, scene_id="E1S01")
            self.assertEqual(self._clip()["repair"]["status"], "running")
            thread.call_args.kwargs["target"]()
        call = self.service.gateway.generate_video.call_args
        self.assertEqual(call.kwargs["ref_videos"], [self.url])
        self.assertEqual(call.kwargs["resolution"], "480p", "a draft stays a draft")
        self.assertIn("画面左下角", call.args[2])
        clip = self._clip()
        self.assertEqual((clip["repair"]["status"], clip["repair"]["previous_url"]), ("done", self.url))
        self.assertEqual(clip["video_url"], fixed)

    def test_the_retake_redoes_only_the_tail_from_that_frame(self):
        tail = _clip(self.temp.name, "tail.mp4", seconds=4, colour="smptebars")
        generate = MagicMock(return_value=(tail, {"mode": "first_frame"}))
        intent = MagicMock()
        req = {"shot_id": 1, "shot_uid": 100101, "vid_prompt": "断水抬刀。", "base_seed": 7}
        earlier = {"video_url": self.url, "stale": True, "retake": {"from_seconds": 3.5, "note": "刀穿手"}}
        url, decision = DramaService._retake_tail(req, earlier, generate, intent, "480p")
        kwargs = generate.call_args.kwargs
        self.assertTrue(kwargs["first_frame"].startswith("data:image/jpeg"))
        self.assertEqual((kwargs["mode"], kwargs["resolution"]), ("first_frame", "480p"))
        self.assertEqual(kwargs["seconds"], 4, "the 2.5 s left are made at the model's 4 s minimum, then trimmed")
        self.assertIn("第 3.5 秒", kwargs["prompt_text"])
        self.assertEqual(req["retaken_from"], 3.5)
        self.assertEqual(decision["retake"]["from_seconds"], 3.5)
        self.assertAlmostEqual(clip_fixes._probe(media_compositor.local_media_path(url))["duration"], 6, delta=0.25)
        # 起点不在片内：不做局部重做，整段照常重出。
        self.assertIsNone(DramaService._retake_tail(req, {**earlier, "retake": {"from_seconds": 9}}, generate, intent, None))
        self.assertIsNone(DramaService._retake_tail(req, {**earlier, "stale": False}, generate, intent, None))


if __name__ == "__main__":
    unittest.main()
