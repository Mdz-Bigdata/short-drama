# -*- coding: utf-8 -*-
"""One-click film on the canvas, and the project's models set from the canvas.

No provider is called: images and clips come from the stub gateway, speech and the compositor are patched.
What is pinned: the film takes the storyboard's clips in storyboard order (one per shot); a silent clip with lines
gets a voice node read in the project's character voices, a clip with sound of its own gets none; music only
when asked and available; the compose node is told which voice is whose and composes them under the right
clips; a second build rewires instead of duplicating; and the four model choices are checked against the model
centre before any is written.
"""

from unittest import mock

from app.core import canvas_film, media_compositor, prompt_data
from app.service import canvas_film as film_service
from app.service import canvas_film_voice, canvas_models
from tests.test_canvas_storyboard import SHOTS
from tests.test_canvas_workspace import CanvasCase, _node, _task


class FilmCase(CanvasCase):
    def setUp(self):
        super().setUp()
        task = _task(shots=[dict(shot) for shot in SHOTS])
        task["assets"]["3_sheets"] = {"林晚": "https://img.test/lin.png"}
        task["assets"]["3_characters"] = [{"name": "林晚", "gender": "女"}, {"name": "周叔", "gender": "男"}]
        self.drama.repo.save_task("t-1", task)
        # This project's video model is treated as one that makes no sound, unless a test says otherwise.
        silent = mock.patch.object(film_service, "uses_native_soundtrack", return_value=False)
        silent.start()
        self.addCleanup(silent.stop)
        self.assertEqual(self.client.post(f"{self.base}/canvas/storyboard", json={}).status_code, 200)

    def canvas(self):
        return self.client.get(f"{self.base}/canvas").json()

    def by_label(self):
        return {node["payload"].get("label"): node for node in self.canvas()["nodes"]}

    def preview(self, **body):
        return self.client.post(f"{self.base}/canvas/film/preview", json=body)

    def build(self, **body):
        response = self.client.post(f"{self.base}/canvas/film", json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()


class PlanTests(FilmCase):
    def test_the_storyboard_clips_play_in_storyboard_order_and_silent_lines_get_a_voice(self):
        preview = self.preview().json()
        self.assertFalse(preview["had_music"])
        self.assertEqual([row["label"] for row in preview["shots"]], ["E1S01 镜1 视频", "E1S01 镜2 视频", "E1S02 镜1 视频"])
        self.assertEqual(preview["shots"][0]["lines"], "林晚：有人吗？")
        self.assertEqual(preview["voiced"], 1)
        self.assertEqual(preview["missing"], {"frames": 2, "pictures": 0, "clips": 3, "voices": 1, "music": 0})
        self.assertEqual(preview["to_run"], 2 + 3 + 1 + 1)

        built = self.build(expected_version=self.canvas()["version"])
        nodes = self.by_label()
        film = nodes[prompt_data.text("canvas_film", "compose_label")]
        self.assertEqual((film["kind"], film["payload"][canvas_film.MARK]), ("video_compose", {"role": "compose"}))
        self.assertEqual(built["compose"], film["id"])
        voice = nodes["E1S01 镜1 视频 · 配音"]
        self.assertEqual((voice["kind"], voice["payload"]["prompt"]), ("audio_gen", "林晚：有人吗？"))
        self.assertEqual(voice["payload"]["params"], {"mode": "speech", "castLines": True})
        clip_ids = [nodes[label]["id"] for label in ("E1S01 镜1 视频", "E1S01 镜2 视频", "E1S02 镜1 视频")]
        self.assertEqual(film["payload"][canvas_film.SOUND_PLAN], {"voices": {clip_ids[0]: voice["id"]}})
        into_film = [edge for edge in self.canvas()["edges"] if edge["target"] == film["id"]]
        self.assertEqual([edge["source"] for edge in into_film if edge["payload"]["role"] == "clip"], clip_ids)
        self.assertEqual(built["run"][-1], film["id"], "the compose node runs last")
        self.assertEqual(set(built["run"]), {
            film["id"], voice["id"], *clip_ids, nodes["E1S01 镜1 首帧"]["id"], nodes["E1S02 镜1 首帧"]["id"],
        })

    def test_a_look_sheet_upstream_of_a_frame_runs_too_and_is_counted_apart(self):
        canvas = self.canvas()
        frame = next(node for node in canvas["nodes"] if node["payload"].get("label") == "E1S01 镜1 首帧")
        sheet = {**_node("sheet", "image_gen", label="林晚·定妆", prompt="林晚的人物定妆照"), "y": -600}
        edges = canvas["edges"] + [{"id": "e_sheet", "source": "sheet", "target": frame["id"], "kind": "reference", "payload": {"role": "ref_image"}}]
        self.put(canvas["nodes"] + [sheet], edges, expected=canvas["version"])
        preview = self.preview().json()
        self.assertEqual((preview["missing"]["frames"], preview["missing"]["pictures"]), (2, 1))
        self.assertIn("sheet", self.build()["run"])

    def test_a_clip_whose_model_makes_sound_gets_no_voice(self):
        with mock.patch.object(film_service, "uses_native_soundtrack", return_value=True):
            preview = self.preview().json()
        self.assertEqual((preview["voiced"], preview["missing"]["voices"]), (0, 0))

    def test_voices_can_be_left_out(self):
        self.assertEqual(self.preview(voices=False).json()["voiced"], 0)

    def test_a_second_build_rewires_the_same_film_instead_of_making_another(self):
        self.build()
        first = self.canvas()
        clip = next(node for node in first["nodes"] if node["payload"].get("label") == "E1S02 镜1 视频")
        again = self.build(node_ids=[clip["id"]])
        second = self.canvas()
        self.assertEqual(len(second["nodes"]), len(first["nodes"]), "no second compose or voice node")
        film = next(node for node in second["nodes"] if node["id"] == again["compose"])
        self.assertEqual([edge["source"] for edge in second["edges"] if edge["target"] == film["id"]], [clip["id"]])
        self.assertEqual(film["payload"][canvas_film.SOUND_PLAN], {"voices": {}})

    def test_picked_clips_off_the_storyboard_play_left_to_right(self):
        canvas = self.canvas()
        extra = [
            {**_node("b", "video_gen", label="乙", prompt="她转身\n台词：周叔：回来！"), "x": 900, "y": 5000},
            {**_node("a", "video_gen", label="甲", prompt="雨夜"), "x": 100, "y": 5000},
        ]
        self.put(canvas["nodes"] + extra, canvas["edges"], expected=canvas["version"])
        preview = self.preview(node_ids=["b", "a"]).json()
        self.assertEqual([row["label"] for row in preview["shots"]], ["甲", "乙"])
        self.assertEqual(preview["shots"][1]["lines"], "周叔：回来！")
        self.assertEqual(preview["voiced"], 1)

    def test_nothing_to_join_and_music_without_a_provider_are_refused(self):
        self.drama.repo.save_task("t-1", _task(shots=[]))
        canvas = self.canvas()
        self.put([node for node in canvas["nodes"] if node["kind"] != "video_gen"], [], expected=canvas["version"])
        refused = self.preview()
        self.assertEqual(refused.status_code, 422)
        self.assertIn(prompt_data.text("canvas_film", "no_clips"), refused.text)

    def test_music_only_when_a_provider_is_there_and_as_long_as_the_film(self):
        with mock.patch.object(media_compositor, "_elevenlabs_available", return_value=False):
            refused = self.preview(music=True)
        self.assertEqual(refused.status_code, 422)
        self.assertIn(prompt_data.text("canvas_film", "no_music"), refused.text)
        with mock.patch.object(media_compositor, "_elevenlabs_available", return_value=True):
            self.build(music=True, music_prompt="悬疑的弦乐")
        self.assertTrue(self.preview().json()["had_music"], "the dialog keeps the film's music on by default")
        music = self.by_label()[prompt_data.text("canvas_film", "music_label")]
        self.assertEqual(music["payload"]["prompt"], "悬疑的弦乐")
        # 5 s + 8 s + no length (5 s), and never shorter than the floor.
        self.assertEqual(music["payload"]["params"], {"mode": "music", "durationSeconds": max(18, prompt_data.number("canvas_film", "min_music_seconds"))})


class RunTests(FilmCase):
    def test_the_whole_film_runs_in_one_batch_and_each_voice_lies_under_its_own_clip(self):
        built = self.build()
        spoken = []

        def speak(segments, *, tts_model, tag):
            spoken.append((segments, tts_model))
            return "/media/voice_1.mp3", "/tmp/voice_1.mp3"

        with mock.patch.object(media_compositor, "synthesize_preferred_dialogue_track", side_effect=speak), \
                mock.patch.object(media_compositor, "compose_film", return_value="/media/film.mp4") as compose, \
                mock.patch.object(media_compositor, "_ffmpeg", return_value="ffmpeg"), \
                mock.patch.object(media_compositor, "clip_has_sound", return_value=False), \
                mock.patch.object(canvas_film_voice.media_compositor, "local_media_path", side_effect=lambda url: f"local:{url}" if url else None):
            answer = self.run_nodes(built["run"], built["version"])
        self.assertEqual(answer["status"], "started", answer)
        self.assertEqual(len(self.gateway.image_calls), 2)
        self.assertEqual(len(self.gateway.video_calls), 3)
        [(segments, model)] = spoken
        self.assertEqual(model, "local-tts")
        self.assertEqual([(line, gender, speaker) for line, gender, _, speaker, _ in segments], [("有人吗？", "female", "林晚")])
        kwargs = compose.call_args.kwargs
        clips = compose.call_args.args[0]
        self.assertEqual(len(clips), 3)
        self.assertEqual(kwargs["shot_voices"], ["local:/media/voice_1.mp3", None, None])
        self.assertIsNone(compose.call_args.args[2], "with a plan, voices go shot by shot, not as one track")
        self.assertEqual(kwargs["native_audio"], [False, False, False])
        outputs = self.client.get(f"{self.base}/canvas/outputs").json()
        self.assertEqual(outputs["outputs"][built["compose"]]["url"], "/media/film.mp4")

    def test_lines_are_voiced_in_each_character_s_voice(self):
        task = self.drama.repo.get_task("t-1")
        segments = canvas_film_voice.cast_segments("林晚：你来了。\n周叔：（低声）快走。", task)
        self.assertEqual([(line, gender, speaker) for line, gender, _, speaker, _ in segments], [("你来了。", "female", "林晚"), ("快走。", "male", "周叔")])


class ShotTableTests(FilmCase):
    def test_a_shot_table_keeps_its_rows_whole_for_laying_out_shots(self):
        import json

        rows = [{"size": "近景", "motion": "推", "seconds": 6, "desc": "林晚推门", "dialogue": "林晚：有人吗？"}]
        self.gateway.call_llm = lambda *args, **kwargs: json.dumps({"shots": rows}, ensure_ascii=False)
        canvas = self.canvas()
        table = {**_node("table", "tool", params={"tool": "shot_table", "model": "deepseek-flash"}, prompt="雨夜，林晚推开老宅的门"), "y": 4000}
        saved = self.put(canvas["nodes"] + [table], canvas["edges"], expected=canvas["version"])
        self.assertEqual(self.run_nodes(["table"], saved["version"])["status"], "started")
        output = self.client.get(f"{self.base}/canvas/outputs").json()["outputs"]["table"]
        self.assertEqual(output["shots"], [{**rows[0], "characters": [], "time": ""}], "a row the model gave no cast or time for still lays out")
        self.assertEqual(len(output["beats"]), 1)


class ModelTests(FilmCase):
    CHOICES = {"text": ["deepseek-flash", "deepseek-v4-pro"], "image": ["seedream", "doubao-seedream-5-0-pro"], "video": ["seedance2.0", "minimax-h3"], "audio": ["local-tts", "eleven_multilingual_v2"]}

    def setUp(self):
        super().setUp()
        listed = mock.patch.object(canvas_models, "choices", side_effect=lambda category: list(self.CHOICES[category]))
        listed.start()
        self.addCleanup(listed.stop)

    def models(self):
        response = self.client.get(f"{self.base}/canvas/models")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_the_four_models_are_shown_with_what_the_centre_enables(self):
        view = self.models()
        self.assertEqual(set(view["models"]), {"text", "image", "video", "audio"})
        self.assertEqual(view["models"]["image"]["chosen"], "seedream")
        self.assertEqual(view["models"]["text"], {"chosen": "", "effective": "deepseek-flash", "choices": self.CHOICES["text"]})
        self.assertFalse(view["running"])

    def test_changing_them_writes_the_project_config(self):
        with mock.patch("app.core.model_gateway.ModelGateway.enabled_video_models", return_value=self.CHOICES["video"]):
            response = self.client.put(f"{self.base}/canvas/models", json={"text": "deepseek-v4-pro", "image": "doubao-seedream-5-0-pro", "video": "minimax-h3", "audio": ""})
        self.assertEqual(response.status_code, 200, response.text)
        config = self.drama.repo.get_task("t-1")["config"]
        self.assertEqual((config["llm_model"], config["image_model"], config["video_model"], config["tts_model"]),
                         ("deepseek-v4-pro", "doubao-seedream-5-0-pro", "minimax-h3", ""))
        self.assertEqual(response.json()["models"]["video"]["chosen"], "minimax-h3")

    def test_a_model_the_centre_does_not_enable_is_refused_and_nothing_is_written(self):
        before = dict(self.drama.repo.get_task("t-1")["config"])
        refused = self.client.put(f"{self.base}/canvas/models", json={"text": "deepseek-v4-pro", "image": "made-up"})
        self.assertEqual(refused.status_code, 422)
        self.assertIn("made-up", refused.text)
        self.assertEqual(self.drama.repo.get_task("t-1")["config"], before)
        self.assertEqual(self.client.put(f"{self.base}/canvas/models", json={"video": ""}).status_code, 422)

    def test_models_do_not_change_while_a_stage_is_running(self):
        task = self.drama.repo.get_task("t-1")
        task["status"] = "running"
        self.drama.repo.save_task("t-1", task)
        refused = self.client.put(f"{self.base}/canvas/models", json={"text": "deepseek-v4-pro"})
        self.assertEqual(refused.status_code, 422)
        self.assertIn(prompt_data.text("canvas_models", "running"), refused.text)

    def test_the_canvas_run_options_list_text_models_too(self):
        options = self.client.get(f"{self.base}/canvas/run-options").json()
        self.assertIn("text", options["models"])
        self.assertIn("text", options["enabled"])
