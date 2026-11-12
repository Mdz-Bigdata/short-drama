# -*- coding: utf-8 -*-
"""第 5 阶段按接法规则出片：同场接上一镜、新角色进场挂定妆照、审核回退链、长镜头段首尾帧、附参考素材不丢。"""

from unittest.mock import patch

from tests.test_stage_five_queue import StageFiveQueueTests, _task

TAIL = "data:image/jpeg;base64,VEFJTA=="
SENSITIVE = "InputImageSensitiveContentDetected 1026 敏感"


class ClipRouteStageFiveTests(StageFiveQueueTests):
    def _run_routes(self, task, *, video=None, failure=""):
        """跑第 5 阶段：尾帧抽取与接缝质检替身化，返回 (存下的任务, 每次视频请求)。"""
        self.calls: list[dict] = []

        def generate_video(model, image_url, prompt, *args, **kwargs):
            self.calls.append({"first": image_url, "prompt": prompt, **kwargs})
            if video is not None:
                return video(len(self.calls))
            return f"https://cdn/{len(self.calls)}.mp4"

        from app.service.drama_service import DramaService

        self.repo.save_task(task["task_id"], task)
        with patch.object(self.service.gateway, "generate_video", side_effect=generate_video), \
             patch.object(self.service.gateway, "generate_image", return_value=("https://cdn/end.png", {})), \
             patch.object(self.service.gateway, "last_video_failure", return_value=failure), \
             patch.object(self.service.gateway, "video_family_ready", return_value=True), \
             patch.object(self.service.gateway, "video_family_modes", return_value=None), \
             patch("app.service.drama_service.media_compositor.extract_last_frame_b64", return_value=TAIL), \
             patch("app.service.drama_service.media_compositor.extract_first_frame_b64", return_value=TAIL), \
             patch("app.service.drama_service.seam_check.compare") as compare, \
             patch("app.service.drama_service.media_compositor.synthesize_preferred_dialogue_track", return_value=(None, None)), \
             patch("app.service.drama_service.media_compositor.attach_audio_to_clip", side_effect=lambda url, *a, **k: url), \
             patch.object(DramaService, "run_real_consistency_check", lambda _self, *a, **k: "OK"):
            compare.return_value.as_dict.return_value = {"verdict": "good", "label": "接上了", "score": 0.01}
            self.service._execute_stage_blocking(task["task_id"], 5, _claimed_task=task)
        return self.repo.get_task(task["task_id"])

    def test_the_next_shot_of_a_scene_opens_on_the_previous_shots_last_frame(self):
        stored = self._run_routes(_task(2))
        self.assertEqual(len(self.calls), 2)
        second = self.calls[1]
        self.assertEqual(second["first"], TAIL)
        self.assertEqual(second.get("ref_images") or [], [], "tailframe 不挂定妆照和场景图")
        clips = stored["assets"]["5"]
        self.assertEqual(clips[1]["clip_route"]["kind"], "tailframe")
        self.assertEqual(clips[1]["first_frame_from"], "镜头 1")
        self.assertEqual(clips[1]["video_route_decision"]["mode"], "first_frame")
        self.assertTrue(clips[1]["video_route_decision"]["reasons"][0].startswith("接法规则："))
        queue = {item["key"]: item for item in stored["assets"]["5_queue"]["items"]}
        self.assertIn("video:1", queue["video:2"]["after"], "等上一镜结束再出")
        self.assertNotIn("video:1", queue["video:2"]["depends_on"], "上一镜失败时本镜不跟着跳过")

    def test_a_new_face_entering_takes_the_tail_as_reference_one_and_the_costume_sheets(self):
        task = _task(2)
        second = task["assets"]["4"][1]
        second["motion_contract"]["characters"] = ["沈砚", "林婉"]
        second.pop("contract_fingerprint")
        stored = self._run_routes(task)
        self.assertEqual(stored["assets"]["5"][1]["clip_route"]["kind"], "tailref")
        request = self.calls[1]
        self.assertIsNone(request["first"])
        self.assertEqual(request["ref_images"][0], TAIL)
        self.assertIn("/media/sheet.png", request["ref_images"])

    def test_a_refused_tail_frame_falls_back_to_the_tail_as_reference_first(self):
        # 第 1 镜出片；第 2 镜首帧接力被审核拦下，退到尾帧当参考图 1 出片。
        stored = self._run_routes(
            _task(2), video=lambda count: None if count == 2 else f"https://cdn/{count}.mp4", failure=SENSITIVE,
        )
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(self.calls[1]["first"], TAIL)
        self.assertIsNone(self.calls[2]["first"])
        self.assertEqual(self.calls[2]["ref_images"][0], TAIL)
        self.assertEqual(stored["assets"]["5"][1]["route_fallback"], ["tailref"])

    def test_when_every_chain_step_is_refused_the_shot_goes_out_on_its_own(self):
        stored = self._run_routes(
            _task(2), video=lambda count: f"https://cdn/{count}.mp4" if count in (1, 4) else None, failure=SENSITIVE,
        )
        self.assertEqual(stored["assets"]["5"][1]["route_fallback"], ["tailref", "independent"])
        independent = self.calls[3]
        self.assertTrue(independent["first"] == "/media/p2.png" or "/media/p2.png" in (independent.get("ref_images") or []))

    def test_a_long_take_part_sends_the_previous_tail_and_its_own_last_storyboard(self):
        task = _task(4)
        task["config"].pop("video_granularity", None)
        for shot in task["assets"]["4"]:
            shot["duration"] = "7"
        stored = self._run_routes(task)
        self.assertEqual([clip["clip_route"]["kind"] for clip in stored["assets"]["5"]], ["first_last", "first_last"])
        first_part, second_part = self.calls
        self.assertEqual((first_part["first"], first_part["last_frame"]), ("/media/p1.png", "/media/p2.png"))
        self.assertEqual((second_part["first"], second_part["last_frame"]), (TAIL, "/media/p4.png"))
        self.assertFalse(any("end.png" in str(call.get("last_frame")) for call in self.calls), "长镜头段的尾帧不另画")

    def test_attached_media_over_the_models_limit_is_refused_not_dropped(self):
        task = _task(1)
        task["assets"]["4"][0]["reference_videos"] = [f"https://cdn/ref{i}.mp4" for i in range(4)]
        task["assets"]["4"][0].pop("contract_fingerprint", None)
        with self.assertRaises(RuntimeError) as failed:
            self._run_routes(task)
        self.assertIn("不悄悄丢掉", str(failed.exception))
        self.assertEqual(self.calls, [])

    def test_turning_the_scene_chain_off_restores_independent_shots(self):
        task = _task(2)
        task["config"]["scene_chain"] = "off"
        stored = self._run_routes(task)
        self.assertNotEqual(self.calls[1]["first"], TAIL)
        self.assertNotEqual((stored["assets"]["5"][1].get("clip_route") or {}).get("kind"), "tailframe")

    def test_draft_mode_asks_for_480p_and_a_shot_sent_back_for_hd_goes_out_at_full_size(self):
        task = _task(2)
        task["config"]["video_draft"] = True
        stored = self._run_routes(task)
        self.assertEqual([call.get("resolution") for call in self.calls], ["480p", "480p"])
        self.assertEqual([clip.get("draft_resolution") for clip in stored["assets"]["5"]], ["480p", "480p"])
        # 第 2 镜样片过了，要重出高清：只有它按全分辨率重出，第 1 镜沿用样片。
        clip = stored["assets"]["5"][1]
        clip["stale"], clip["hd_retake"] = True, True
        stored = self._run_routes(stored)
        self.assertEqual([call.get("resolution") for call in self.calls], [None])
        self.assertNotIn("draft_resolution", stored["assets"]["5"][1])
        self.assertEqual(stored["assets"]["5"][0]["draft_resolution"], "480p")


# 父类的逐镜队列测试在本类里不重复跑。
for _inherited in [name for name in vars(StageFiveQueueTests) if name.startswith("test_")]:
    setattr(ClipRouteStageFiveTests, _inherited, None)
