# -*- coding: utf-8 -*-
"""镜头衔接：光线词固定、基调词统一、首尾帧接力。"""

import unittest
from unittest.mock import patch

from app.core import frame_handoff
from app.core.genre_clusters import get_cluster
from app.core.style_packs import DEFAULT_PACK_ID, get_pack
from tests.test_stage_five_queue import StageFiveQueueTests, _task


class LightPhraseTests(unittest.TestCase):
    def test_the_light_clauses_of_the_establishing_shot_are_taken_verbatim(self):
        desc = (
            "真人实拍古装质感，雨夜演武场，青石铺地；唯一主光为画面左后方火把的暖橙硬光，在他左脸打出一条明确的明暗交界线，"
            "光比约6:1；镜头缓慢推近，他抬手握住剑柄，看向画面右侧。"
        )
        phrase = frame_handoff.light_phrase(desc)
        self.assertEqual(phrase, "唯一主光为画面左后方火把的暖橙硬光，在他左脸打出一条明确的明暗交界线，光比约6:1")
        self.assertNotIn("推近", phrase)
        self.assertNotIn("握住", phrase)

    def test_a_light_named_without_a_direction_or_on_a_prop_is_not_a_light_phrase(self):
        self.assertEqual(frame_handoff.light_phrase("右手拇指青白玉扳指在冷光里透出微绿；他站着不动"), "")
        self.assertEqual(frame_handoff.light_phrase("冷青天光自右前方切来"), "冷青天光自右前方切来")

    def test_every_scene_gets_the_phrase_of_its_first_shot_that_has_one(self):
        shots = [
            {"scene_id": "E1S01", "desc": "他走进来"},
            {"scene_id": "E1S01", "desc": "主光为窗外冷白天光，光比约4:1"},
            {"scene_id": "E1S01", "desc": "主光换成烛光"},
            {"scene_id": "E1S02", "desc": "没有写光"},
        ]
        self.assertEqual(frame_handoff.scene_light_phrases(shots), {"E1S01": "主光为窗外冷白天光，光比约4:1"})


class BoardLightingTests(unittest.TestCase):
    def test_the_time_of_day_is_read_from_the_scene_heading(self):
        self.assertEqual(frame_handoff.scene_time("演武场 雨夜 外景 沈无咎撑着膝盖站起"), "雨夜，外景")
        self.assertEqual(frame_handoff.scene_time("演武场 廊下 雨夜 外景 廊檐前雨线成帘"), "雨夜，外景")
        self.assertEqual(frame_handoff.scene_time("雨夜长街 深夜 外景 沈无咎在长街中央停下"), "深夜，外景")
        self.assertEqual(frame_handoff.scene_time("剑冢 白日 内景 剑冢石门半开"), "白日，内景")
        self.assertEqual(frame_handoff.scene_time("沈无咎撑着膝盖站起"), "")

    def test_every_panel_is_told_the_night_and_the_key_light(self):
        line = frame_handoff.board_lighting("演武场 雨夜 外景 沈无咎站起", "火把的橙红硬光贴着雨幕斜射进来")
        self.assertIn("雨夜，外景", line)
        self.assertIn("不得画成白天或阴天的天光", line)
        self.assertIn("主光：火把的橙红硬光贴着雨幕斜射进来", line)
        self.assertNotIn("不得画成白天", frame_handoff.board_lighting("剑冢 白日 内景 石门半开"))

    def test_without_a_heading_or_light_the_old_wording_stays(self):
        self.assertEqual(frame_handoff.board_lighting("", ""), frame_handoff.DEFAULT_BOARD_LIGHTING)


class LocationStandInTests(unittest.TestCase):
    HEADINGS = {
        "E1S07": "演武场 雨夜 外景 …", "E1S08": "剑冢 石门外 雨夜 内景 …", "E1S09": "演武场 雨夜 外景 …",
        "E1S10": "演武场 雨夜 外景 …", "E2S11": "演武场 入夜 外景 …", "E2S01": "剑冢 白日 内景 …",
    }

    @staticmethod
    def _clip(scene_id, url, location="演武场", **extra):
        return {"scene_id": scene_id, "video_url": url, "mention_kinds": {"沈无咎": "actor", location: "scene"}, **extra}

    def test_scene_slots_follow_the_main_view(self):
        entries = [("actor", "沈无咎", "a"), ("scene", "演武场", "s"), ("scene", "", "s45"), ("prop", "钥匙", "p"), ("scene", "", "sd")]
        self.assertEqual(frame_handoff.scene_ref_slots(entries), [(1, "演武场"), (2, "演武场"), (4, "演武场")])

    def test_stand_ins_are_shot_clips_of_the_same_place_and_hour_nearest_first(self):
        clips = [
            self._clip("E1S07", "/media/s07.mp4"),
            self._clip("E1S08", "/media/s08.mp4", location="剑冢"),            # 别的场地
            self._clip("E1S09", "/media/s09.mp4"),                             # 本场自己
            self._clip("E1S10", "/media/s10.mp4"),
            self._clip("E2S11", "/media/e2s11.mp4"),                           # 入夜，不是雨夜
            self._clip("E1S10", "/media/s10b.mp4", moderation_fallback={"dropped": "storyboard_frames"}),
            self._clip("E1S07", "/media/s07old.mp4", stale=True),
        ]
        self.assertEqual(
            frame_handoff.stand_in_clips(clips, self.HEADINGS, "E1S09", "演武场", 3),
            ["/media/s10.mp4", "/media/s07.mp4"],
        )

    def test_the_service_swaps_only_the_location_images_in_place(self):
        from app.service.drama_service import DramaService

        task = {"assets": {"5": [self._clip("E1S10", "/media/s10.mp4"), self._clip("E1S07", "/media/s07.mp4")]}}
        req = {"shot": {"scene_id": "E1S09"}, "scene_ref_slots": [(1, "演武场"), (2, "演武场")]}
        scenes = [{"scene_id": sid, "content": heading} for sid, heading in self.HEADINGS.items()]
        with patch.object(DramaService, "_breakdown_scenes", return_value=scenes), \
             patch("app.service.drama_service.media_compositor.local_media_path", side_effect=lambda url: f"/disk{url}"), \
             patch("app.service.drama_service.media_compositor.extract_last_frame_b64", side_effect=lambda path: f"data:{path}"):
            images, swapped = DramaService._location_stand_ins(DramaService.__new__(DramaService), task, req, ["actor.png", "day.png", "day45.png", "prop.png"])
        self.assertEqual(swapped, 2)
        self.assertEqual(images, ["actor.png", "data:/disk/media/s10.mp4", "data:/disk/media/s07.mp4", "prop.png"])

    def test_no_stand_in_when_the_scene_has_no_stated_hour(self):
        clips = [self._clip("E1S10", "/media/s10.mp4")]
        self.assertEqual(frame_handoff.stand_in_clips(clips, {"E1S09": "演武场"}, "E1S09", "演武场", 2), [])


class ToneTests(unittest.TestCase):
    def test_the_show_is_toned_by_its_genre_cluster(self):
        tone = frame_handoff.tone_for(get_pack(DEFAULT_PACK_ID), get_cluster("B"))
        self.assertTrue(tone.startswith("古装权谋江湖调性 + "))
        self.assertNotIn("都市剧情调性", tone)

    def test_a_fight_scene_swaps_the_tempo_slot_for_a_fight_tempo(self):
        pack = get_pack(DEFAULT_PACK_ID)
        tone = frame_handoff.tone_for(pack, get_cluster("B"), fight=True)
        self.assertTrue(tone.startswith("古装权谋江湖调性 + 蓄力后爆发的打斗节奏、拳拳到肉 + "))
        self.assertNotIn("稳健节奏", tone)
        self.assertIn("稳健节奏", frame_handoff.tone_for(pack, get_cluster("B")))
        for pack_id in ("film_35mm", "atom_punk", "anime_2d_cel", "anime_3d_cg"):
            self.assertIn(frame_handoff.FIGHT_TEMPO, frame_handoff.tone_for(get_pack(pack_id), None, fight=True), pack_id)

    def test_a_default_cyberpunk_style_does_not_leak_into_a_period_drama(self):
        self.assertEqual(frame_handoff.coherent_director_style("cyberpunk", "B"), frame_handoff.FALLBACK_DIRECTOR_STYLE)
        self.assertEqual(frame_handoff.coherent_director_style("cyberpunk", "F"), "cyberpunk")
        self.assertEqual(frame_handoff.coherent_director_style("palace", "B"), "palace")

    def test_the_cluster_follows_the_storyboards_then_the_title(self):
        boards = {f"E1S0{n}": {"direction": {"cluster": "B" if n < 3 else "D"}} for n in range(1, 5)}
        self.assertEqual(frame_handoff.show_cluster({"assets": {"4_scene_boards": boards}}).id, "B")
        self.assertEqual(frame_handoff.show_cluster({"config": {"title_suggestion": "请帮我生成一份武侠短剧"}}, genre="wuxia").id, "B")


class StageFiveHandoffTests(StageFiveQueueTests):
    """沿用第 5 阶段队列测试的替身。"""

    def test_every_shot_of_a_scene_carries_the_same_light_lock(self):
        task = _task(3)
        first = task["assets"]["4"][0]
        first["desc"] = first["motion_contract"]["subject_action"] = "沈砚推门而入，主光为画面右侧窗外的冷白天光，光比约4:1"
        first.pop("contract_fingerprint")          # 描述改了，契约跟着改；旧指纹作废
        prompts: list[str] = []
        stored = self._run(task, on_video=prompts.append)
        locks = {line for prompt in prompts for line in prompt.splitlines() if line.startswith("[光影锁]")}
        self.assertEqual(locks, {"[光影锁]主光为画面右侧窗外的冷白天光，光比约4:1"})
        self.assertEqual(len(stored["assets"]["5"]), 3)

    def test_the_tone_line_follows_the_genre_not_the_default_style(self):
        task = _task(1)
        task["config"]["director_style"] = "cyberpunk"
        prompts: list[str] = []
        self._run(task, on_video=prompts.append)
        self.assertNotIn("cyberpunk", prompts[0])
        self.assertNotIn("都市剧情调性", prompts[0])

    def test_the_second_part_of_a_split_board_opens_on_the_first_parts_last_frame(self):
        task = _task(2)
        task["config"].pop("video_granularity", None)
        for shot in task["assets"]["4"]:
            shot["duration"] = "10"            # 两个 10 秒瞬间放不进一次 15 秒请求：切成两段
        calls: list[dict] = []

        def video(model, image_url, prompt, *args, **kwargs):
            calls.append({"first": image_url, "refs": list(kwargs.get("ref_images") or []), "prompt": prompt})
            return f"https://cdn/{len(calls)}.mp4"

        with patch("app.service.drama_service.media_compositor.extract_last_frame_b64", return_value="data:image/jpeg;base64,TEFTVA==") as extract, \
             patch("app.service.drama_service.seam_check.compare") as compare:
            compare.return_value.as_dict.return_value = {"verdict": "good", "label": "接上了", "score": 0.01}
            with patch("app.service.drama_service.media_compositor.extract_first_frame_b64", return_value="data:image/jpeg;base64,TEFTVA=="):
                stored = self._run_with_video(task, video)
        self.assertEqual(len(calls), 2)
        # The seam of the continued part is checked and kept with the clip; the first part has no seam.
        self.assertEqual([clip.get("seam") for clip in stored["assets"]["5"]], [None, {"verdict": "good", "label": "接上了", "score": 0.01}])
        extract.assert_called_once()
        self.assertEqual(extract.call_args.args[0], "https://cdn/1.mp4")
        second = calls[1]
        self.assertIn("data:image/jpeg;base64,TEFTVA==", [second["first"], *second["refs"]])
        # The words catch the first part's ending before saying what the second part does.
        self.assertIn("上一段结尾：", second["prompt"])
        self.assertNotIn("上一段结尾：形成下一格", second["prompt"])
        self.assertNotIn("上一段结尾：", calls[0]["prompt"])
        clips = stored["assets"]["5"]
        self.assertEqual([clip.get("first_frame_from") for clip in clips], [None, "E1S01 片段 1/2"])
        queue = {item["key"]: item for item in stored["assets"]["5_queue"]["items"]}
        self.assertIn("video:1", queue["video:2"]["depends_on"])

    def test_a_reused_first_part_hands_over_from_its_saved_clip(self):
        task = _task(2)
        task["config"].pop("video_granularity", None)
        for shot in task["assets"]["4"]:
            shot["duration"] = "10"
        calls: list[str] = []
        with patch("app.service.drama_service.media_compositor.extract_last_frame_b64", return_value="data:image/jpeg;base64,TEFTVA=="):
            first = self._run_with_video(task, lambda m, i, p, *a, **k: calls.append(p) or f"https://cdn/{len(calls)}.mp4")
        # 真实运行里入片后的片段是本地文件(配好音轨)，与供应商的原始链接不是同一个地址。
        saved = first["assets"]["5"][0]["video_url"] = "/media/shotav_part1.mp4"
        first["status"] = "running"
        first["workflow_control"] = {"run_id": "run-2", "active": True, "pause_requested": False}
        first["assets"]["5"][1]["stale"] = True           # 只重做第 2 段；第 1 段复用上一轮
        seen: list[str] = []

        def extract(source):
            seen.append(source)
            return None if source == "https://cdn/1.mp4" else "data:image/jpeg;base64,TEFTVA=="   # 供应商链接已失效

        with patch("app.service.drama_service.media_compositor.extract_last_frame_b64", side_effect=extract), \
             patch("app.service.drama_service.media_compositor.media_available", return_value=True):   # 替身文件视为在盘
            again = self._run_with_video(first, lambda m, i, p, *a, **k: "https://cdn/3.mp4")
        self.assertEqual(seen, ["https://cdn/1.mp4", saved])
        self.assertEqual(again["assets"]["5"][1]["first_frame_from"], "E1S01 片段 1/2")

    def test_a_continued_part_without_its_parents_last_frame_is_not_generated(self):
        """The seam of one continuous shot: with no last frame to open on, the second part is refused, never a clip that jumps."""
        task = _task(2)
        task["config"].pop("video_granularity", None)
        for shot in task["assets"]["4"]:
            shot["duration"] = "10"
        calls: list[dict] = []

        def video(model, image_url, prompt, *args, **kwargs):
            calls.append({"first": image_url})
            return f"https://cdn/{len(calls)}.mp4"

        with patch("app.service.drama_service.media_compositor.extract_last_frame_b64", return_value=None), \
             self.assertRaises(RuntimeError) as failed:
            self._run_with_video(task, video)
        self.assertIn("尾帧", str(failed.exception))
        self.assertEqual(len(calls), 1)
        queue = {item["key"]: item for item in self.repo.get_task(task["task_id"])["assets"]["5_queue"]["items"]}
        self.assertEqual(queue["video:1"]["status"], "done")
        self.assertEqual(queue["video:2"]["status"], "failed")

    def _run_with_video(self, task, video):
        self.repo.save_task(task["task_id"], task)
        from app.service.drama_service import DramaService

        with patch.object(self.service.gateway, "generate_video", side_effect=video), \
             patch.object(self.service.gateway, "generate_image", return_value=("https://cdn/frame.png", {})), \
             patch.object(self.service.gateway, "video_family_ready", return_value=True), \
             patch.object(self.service.gateway, "video_family_modes", return_value=None), \
             patch("app.service.drama_service.media_compositor.synthesize_preferred_dialogue_track", return_value=(None, None)), \
             patch("app.service.drama_service.media_compositor.attach_audio_to_clip", side_effect=lambda url, *a, **k: url), \
             patch.object(DramaService, "run_real_consistency_check", lambda _self, *a, **k: "OK"):
            self.service._execute_stage_blocking(task["task_id"], 5, _claimed_task=task)
        return self.repo.get_task(task["task_id"])

    # 父类的逐镜测试在本类里不重复跑。
    test_shots_are_generated_under_the_video_ceiling_and_the_queue_is_persisted = None
    test_a_queued_shot_can_be_withdrawn_while_another_runs_and_the_finished_ones_are_kept = None
    test_the_queue_api_lists_items_and_refuses_to_cancel_a_running_one = None
    test_a_restart_requeues_items_a_dead_run_left_running = None
    test_a_provider_that_returns_no_clip_fails_the_shot_with_its_reason = None
    test_a_rerun_reuses_clips_without_regenerating_their_end_frames = None
    test_a_rerun_makes_again_a_clip_whose_link_has_expired = None
    test_a_rerun_reuses_the_saved_copy_when_only_the_provider_link_expired = None
    test_a_clip_sent_back_for_a_retake_is_not_returned_through_its_own_job = None
    test_a_board_whose_frame_is_judged_sensitive_is_retried_without_the_frames = None
    test_identity_references_prefer_local_views_over_expiring_sheet_links = None


if __name__ == "__main__":
    unittest.main()

