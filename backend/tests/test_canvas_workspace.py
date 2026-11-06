"""The node canvas's backend: boards, revisions, running nodes behind the gate, history, commit, and the agent's tools.

Every provider call is a stub: nothing here can reach a paid model.
"""

import base64
import io
import json
import os
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from app.api.auth_api import get_current_user
from app.api.studio_api import get_drama_service, get_studio_service
from app.core import media_compositor, studio_canvas
from app.core.agent_tools import catalog
from app.repository.studio_repo import StudioRepository
from app.repository.task_repo import TaskRepository
from app.schema.studio import CanvasEdge, CanvasNode, CanvasPutRequest, ProjectCreate
from app.service import studio_canvas_runs
from app.service.director_desk_service import ASSET_KEY
from app.service.drama_service import DramaService
from app.service.studio_service import StudioService
from main import app


class StubGateway:
    def __init__(self):
        self.image_calls = []
        self.video_calls = []
        self.fail_with = None
        self.seedance_prompt_opt = True

    def validate_image_request(self, model, ref_images=None, *, require_reference_support=False):
        return None

    def generate_image(self, model, prompt, ref_images=None, size=None, *, enhance_prompt=True, require_reference_support=False):
        self.image_calls.append({"model": model, "prompt": prompt, "ref_images": ref_images, "size": size})
        if self.fail_with:
            raise RuntimeError(self.fail_with)
        return f"/media/image_{len(self.image_calls)}.png", "stub"

    def generate_video(self, model, image_url, prompt, prefer_provider=None, last_frame=None, ref_images=None, ref_videos=None, ref_audios=None, duration=5, seed=None, style_pack=None):
        self.video_calls.append({"model": model, "first_frame": image_url, "last_frame": last_frame, "prompt": prompt, "ref_images": ref_images, "ref_videos": ref_videos, "duration": duration})
        return f"/media/video_{len(self.video_calls)}.mp4"

    def video_clip_ceiling(self, model):
        return 15


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def _node(node_id, kind, **payload):
    return {"id": node_id, "kind": kind, "track": "freezone", "x": 0, "y": 0, "width": 200, "height": 100, "artifact_id": None, "payload": payload}


def _edge(source, target, role=None, kind="reference"):
    return {"id": f"{source}-{target}", "source": source, "target": target, "kind": kind, "payload": {"role": role} if role else {}}


def _task(task_id="t-1", owner="u1", shots=None):
    return {
        "task_id": task_id, "owner_user_id": owner, "status": "idle", "current_stage": 4,
        "config": {"title_suggestion": "雨夜来信", "video_model": "seedance2.0", "image_model": "seedream", "tts_model": "local-tts"},
        "assets": {"4": shots if shots is not None else [
            {"scene_id": "E1S01", "shot_id": 1, "shot_uid": 101, "desc": "推门"},
            {"scene_id": "E1S01", "shot_id": 2, "shot_uid": 102, "desc": "回头", "reference_videos": ["/media/old.mp4"]},
            {"scene_id": "E1S02", "shot_id": 1, "shot_uid": 103, "desc": "雨街"},
        ]},
        "logs": {}, "chat_history": [],
    }


# The module's real function, taken before any test patches it.
KEEP_MEDIA = studio_canvas_runs._keep_media


class CanvasCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.studio = StudioService(StudioRepository(root / "studio.sqlite3"))
        # A run happens inside the request here; in production it is a daemon thread.
        self.studio.canvas_runs._spawn = lambda work: work()
        self.drama = DramaService()
        self.drama.repo = TaskRepository(str(root / "tasks.json"))
        self.gateway = StubGateway()
        self.drama.gateway = self.gateway
        self.drama.repo.save_task("t-1", _task())
        self.drama.repo.save_task("t-2", _task("t-2", owner="someone-else"))
        self.user = {"user_id": "u1", "role": "user"}

        app.dependency_overrides[get_current_user] = lambda: self.user
        app.dependency_overrides[get_studio_service] = lambda: self.studio
        app.dependency_overrides[get_drama_service] = lambda: self.drama
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

        keeper = patch.object(studio_canvas_runs, "_keep_media", side_effect=lambda url, medium, tag: {"url": str(url)})
        keeper.start()
        self.addCleanup(keeper.stop)

        opened = self.client.post("/api/studio/tasks/t-1/canvas-project")
        self.assertEqual(opened.status_code, 200, opened.text)
        self.project = opened.json()["project_id"]
        self.base = f"/api/studio/projects/{self.project}"

    def put(self, nodes, edges=(), expected=0, canvas_id=None):
        response = self.client.put(
            f"{self.base}/canvas", params={"canvas_id": canvas_id} if canvas_id else None,
            json={"expected_version": expected, "nodes": list(nodes), "edges": list(edges)},
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def run_nodes(self, node_ids, version, confirm=True, op="op-1", confirmed=None):
        response = self.client.post(f"{self.base}/canvas/runs", json={
            "expected_version": version, "node_ids": node_ids, "operation_id": op, "confirm": confirm,
            "confirmed_request_durations": confirmed or [],
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()


class ProjectAndBoardTests(CanvasCase):
    def test_a_task_has_one_project_per_person_and_other_peoples_tasks_are_hidden(self):
        self.assertEqual(self.client.post("/api/studio/tasks/t-1/canvas-project").json()["project_id"], self.project)
        self.assertEqual(self.client.post("/api/studio/tasks/t-2/canvas-project").status_code, 404)
        self.assertEqual(self.client.post("/api/studio/tasks/nope/canvas-project").status_code, 404)
        self.user = {"user_id": "intruder", "role": "user"}
        self.assertEqual(self.client.get(f"{self.base}/canvas").status_code, 404)
        self.assertEqual(self.client.get(f"{self.base}/canvases").status_code, 404)
        self.assertEqual(self.client.post(f"{self.base}/canvas/runs", json={"expected_version": 0, "node_ids": ["a"], "operation_id": "abc"}).status_code, 404)

    def test_old_canvases_still_load_and_new_kinds_save(self):
        # Written straight to the repository the way older code did, with the old five kinds only.
        repo = self.studio.repository
        repo.put_canvas(self.project, "u1", CanvasPutRequest(
            expected_version=0,
            nodes=[CanvasNode(id="m", kind="media", track="mainline", x=1, y=2, width=3, height=4, payload={"label": "旧素材"}),
                   CanvasNode(id="n", kind="note", track="freezone", x=5, y=6, width=7, height=8)],
            edges=[CanvasEdge(id="e", source="m", target="n", kind="lineage")],
        ))
        loaded = self.client.get(f"{self.base}/canvas").json()
        self.assertEqual({node["kind"] for node in loaded["nodes"]}, {"media", "note"})
        self.assertEqual(loaded["canvas_id"], "main")
        kinds = ["image_gen", "video_gen", "audio_gen", "video_compose", "style_ref", "panorama", "previz", "group", "note", "media"]
        saved = self.put([_node(f"k{index}", kind) for index, kind in enumerate(kinds)], expected=loaded["version"])
        self.assertEqual(saved["version"], loaded["version"] + 1)
        bad = self.client.put(f"{self.base}/canvas", json={"expected_version": saved["version"], "nodes": [_node("x", "not-a-kind")], "edges": []})
        self.assertEqual(bad.status_code, 422)

    def test_a_stale_save_is_refused_not_merged(self):
        self.put([_node("a", "note")])
        stale = self.client.put(f"{self.base}/canvas", json={"expected_version": 0, "nodes": [], "edges": []})
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(len(self.client.get(f"{self.base}/canvas").json()["nodes"]), 1)

    def test_boards_are_independent_and_bookmarks_do_not_bump_the_version(self):
        self.put([_node("a", "note")])
        board = self.client.post(f"{self.base}/canvases", json={"title": "第二张"}).json()
        self.assertEqual(self.client.get(f"{self.base}/canvas", params={"canvas_id": board["id"]}).json()["version"], 0)
        self.put([_node("b", "note"), _node("c", "note")], canvas_id=board["id"])
        self.assertEqual(len(self.client.get(f"{self.base}/canvas").json()["nodes"]), 1)
        listed = {item["id"]: item for item in self.client.get(f"{self.base}/canvases").json()}
        self.assertEqual((listed["main"]["version"], listed[board["id"]]["version"]), (1, 1))

        patched = self.client.patch(f"{self.base}/canvases/{board['id']}", json={"bookmarks": [{"slot": 1, "x": 10, "y": 20, "zoom": 0.5}], "title": "改名"}).json()
        self.assertEqual((patched["title"], patched["bookmarks"][0]["slot"], patched["version"]), ("改名", 1, 1))
        main = self.client.patch(f"{self.base}/canvases/main", json={"bookmarks": [{"slot": 2, "x": 0, "y": 0, "zoom": 1}]}).json()
        self.assertEqual((main["id"], main["version"]), ("main", 1))
        self.assertEqual(self.client.patch(f"{self.base}/canvases/main", json={"bookmarks": [{"slot": 2, "x": 0, "y": 0, "zoom": 1}, {"slot": 2, "x": 1, "y": 1, "zoom": 1}]}).status_code, 422)

        self.assertEqual(self.client.delete(f"{self.base}/canvases/main").status_code, 422)
        self.assertEqual(self.client.delete(f"{self.base}/canvases/{board['id']}").status_code, 200)
        self.assertEqual(self.client.get(f"{self.base}/canvas", params={"canvas_id": board["id"]}).status_code, 404)
        self.assertEqual([item["id"] for item in self.client.get(f"{self.base}/canvases").json()], ["main"])

    def test_versions_are_listed_and_a_restore_is_a_new_version(self):
        self.put([_node("a", "note", label="一")])
        self.put([_node("a", "note", label="二"), _node("b", "note")], expected=1)
        versions = self.client.get(f"{self.base}/canvas/versions").json()["versions"]
        self.assertEqual([(item["version"], item["node_count"]) for item in versions], [(2, 2), (1, 1)])
        self.assertEqual(self.client.post(f"{self.base}/canvas/versions/1/restore", json={"expected_version": 1}).status_code, 409)
        self.assertEqual(self.client.post(f"{self.base}/canvas/versions/99/restore", json={"expected_version": 2}).status_code, 422)
        restored = self.client.post(f"{self.base}/canvas/versions/1/restore", json={"expected_version": 2}).json()
        self.assertEqual((restored["version"], restored["nodes"][0]["payload"]["label"]), (3, "一"))
        self.assertEqual(len(self.client.get(f"{self.base}/canvas/versions").json()["versions"]), 3)

    def test_autosave_history_is_thinned_but_the_latest_always_survives(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        rows = [(version, (now + timedelta(minutes=version)).isoformat()) for version in range(1, 301)]
        dropped = set(studio_canvas.versions_to_prune(rows))
        self.assertNotIn(300, dropped)
        self.assertFalse(dropped & set(range(251, 301)), "the newest fifty stay")
        self.assertGreater(len(dropped), 200)
        hours = {datetime.fromisoformat(created).strftime("%d%H") for version, created in rows if version <= 250}
        kept_old = [version for version, _ in rows if version <= 250 and version not in dropped]
        self.assertEqual({datetime.fromisoformat(dict(rows)[version]).strftime("%d%H") for version in kept_old}, hours)
        self.assertLessEqual(len(kept_old), len(hours) + 1, "one per hour among the older ones, then one per day")
        # Through the real write path: saving version 20 thins nothing yet and never loses the head.
        version = 0
        for _ in range(20):
            version = self.put([_node("a", "note")], expected=version)["version"]
        self.assertEqual(self.client.get(f"{self.base}/canvas").json()["version"], 20)

    def test_uploads_are_judged_by_their_bytes(self):
        with tempfile.TemporaryDirectory() as media, patch.object(media_compositor, "MEDIA_DIR", media):
            image = self.client.post(f"{self.base}/canvas/uploads", files={"file": ("a.png", _png(), "image/png")})
            self.assertEqual(image.status_code, 200, image.text)
            self.assertEqual(image.json()["medium"], "image")
            self.assertEqual(image.json()["provenance"]["origin"], "upload")
            self.assertTrue(os.path.basename(image.json()["url"]).startswith("canvas_up_"))
            video = self.client.post(f"{self.base}/canvas/uploads", files={"file": ("a.mp4", b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 40, "video/mp4")})
            self.assertEqual(video.json()["medium"], "video")
            audio = self.client.post(f"{self.base}/canvas/uploads", files={"file": ("a.mp3", b"ID3" + b"\x00" * 64, "audio/mpeg")})
            self.assertEqual(audio.json()["medium"], "audio")
            for name, content, declared in (("x.html", b"<script>alert(1)</script>", "image/png"), ("y.svg", b"<svg onload=alert(1)>", "image/svg+xml"), ("z.mp3", b"not audio", "audio/mpeg")):
                refused = self.client.post(f"{self.base}/canvas/uploads", files={"file": (name, content, declared)})
                self.assertEqual(refused.status_code, 422, name)
            self.assertEqual(len(os.listdir(media)), 3)

    def test_the_archive_carries_further_canvases_and_history(self):
        board = self.client.post(f"{self.base}/canvases", json={"title": "第二张"}).json()
        self.put([_node("img", "image_gen", prompt="雨夜")], canvas_id=board["id"])
        self.put([_node("img", "image_gen", prompt="雨夜")])
        self.run_nodes(["img"], 1)
        content = self.studio.export_project_archive(self.project, "u1")
        imported = self.studio.import_project_archive(content, owner_id="u9", project_name="副本")
        copy_id = imported["id"]
        self.assertEqual({item.id for item in self.studio.repository.list_canvases(copy_id, "u9")}, {"main", board["id"]})
        self.assertEqual(self.studio.repository.get_canvas(copy_id, "u9", canvas_id=board["id"]).nodes[0].id, "img")
        self.assertEqual(self.studio.canvas_outputs(copy_id, "u9")["outputs"]["img"]["url"], "/media/image_1.png")


class RunTests(CanvasCase):
    def test_nothing_is_spent_without_confirmation(self):
        saved = self.put([_node("img", "image_gen", prompt="雨夜街道")])
        answer = self.run_nodes(["img"], saved["version"], confirm=False)
        self.assertEqual(answer["status"], "needs_confirmation")
        self.assertEqual(answer["assessment"]["decision"], "admitted")
        self.assertEqual(self.gateway.image_calls, [])
        self.assertEqual(self.client.get(f"{self.base}/canvas/nodes/img/history").json()["runs"], [])
        # Assessing alone never spends either.
        self.client.post(f"{self.base}/canvas/runs/assess", json={"node_ids": ["img"]})
        self.assertEqual(self.gateway.image_calls, [])

    def test_a_run_appends_to_history_and_retrying_the_same_order_is_not_a_second_bill(self):
        saved = self.put([_node("img", "image_gen", prompt="雨夜街道", params={"size": "1024x1024", "model": "seedream-x"})])
        first = self.run_nodes(["img"], saved["version"], op="op-a")
        self.assertEqual((first["status"], first["reused"]), ("started", False))
        again = self.run_nodes(["img"], saved["version"], op="op-a")
        self.assertTrue(again["reused"])
        self.assertEqual(len(self.gateway.image_calls), 1)
        self.assertEqual(self.gateway.image_calls[0]["model"], "seedream-x")
        self.run_nodes(["img"], saved["version"], op="op-b")
        history = self.client.get(f"{self.base}/canvas/nodes/img/history").json()
        self.assertEqual([run["status"] for run in history["runs"]], ["done", "done"])
        self.assertEqual(history["active_run_id"], history["runs"][0]["id"])
        self.assertEqual(history["runs"][0]["output"]["provenance"]["origin"], "canvas_run")
        # A finished job must not have touched the document anyone is editing.
        self.assertEqual(self.client.get(f"{self.base}/canvas").json()["version"], saved["version"])
        outputs = self.client.get(f"{self.base}/canvas/outputs").json()
        self.assertEqual(outputs["outputs"]["img"]["url"], "/media/image_2.png")
        self.assertEqual((outputs["running"], outputs["history_counts"]["img"]), (0, 2))

    def test_restore_and_delete_a_past_result(self):
        saved = self.put([_node("img", "image_gen", prompt="雨夜街道")])
        self.run_nodes(["img"], saved["version"], op="op-a")
        self.run_nodes(["img"], saved["version"], op="op-b")
        newer, older = self.client.get(f"{self.base}/canvas/nodes/img/history").json()["runs"]
        restored = self.client.post(f"{self.base}/canvas/nodes/img/history/{older['id']}/restore").json()
        self.assertEqual(restored["active_run_id"], older["id"])
        self.assertEqual(self.client.get(f"{self.base}/canvas/outputs").json()["outputs"]["img"]["url"], older["output"]["url"])
        # Deleting what is shown falls back to what is left; the row stays on disk, hidden.
        after = self.client.delete(f"{self.base}/canvas/nodes/img/history/{older['id']}").json()
        self.assertEqual(after["active_run_id"], newer["id"])
        self.assertEqual(len(after["runs"]), 1)
        self.assertEqual(self.studio.repository._connection.execute("SELECT COUNT(*) FROM canvas_node_runs").fetchone()[0], 2)
        self.assertEqual(self.client.post(f"{self.base}/canvas/nodes/img/history/{older['id']}/restore").status_code, 404)
        # A new generation takes over from a restored one.
        self.client.post(f"{self.base}/canvas/nodes/img/history/{newer['id']}/restore")
        self.run_nodes(["img"], saved["version"], op="op-c")
        latest = self.client.get(f"{self.base}/canvas/nodes/img/history").json()
        self.assertEqual(latest["active_run_id"], latest["runs"][0]["id"])

    def test_an_image_upstream_becomes_a_reference_input_of_a_video_node(self):
        saved = self.put(
            [
                _node("up", "media", output={"medium": "image", "url": "/media/up.png"}),
                _node("end", "media", output={"medium": "image", "url": "/media/end.png"}),
                _node("txt", "note", text="冷色调"),
                _node("sty", "style_ref", styleText="胶片颗粒"),
                _node("vid", "video_gen", prompt="她转身", params={"durationSeconds": 8}),
            ],
            [_edge("up", "vid", "first_frame"), _edge("end", "vid", "last_frame"), _edge("txt", "vid", kind="dependency"), _edge("sty", "vid")],
        )
        answer = self.run_nodes(["vid"], saved["version"])
        self.assertEqual(answer["status"], "started", answer)
        call = self.gateway.video_calls[0]
        self.assertEqual((call["first_frame"], call["last_frame"], call["duration"]), ("/media/up.png", "/media/end.png", 8))
        for part in ("她转身", "冷色调", "胶片颗粒"):
            self.assertIn(part, call["prompt"])

    def test_one_unrunnable_node_holds_the_whole_batch_back(self):
        saved = self.put([_node("img", "image_gen", prompt="好"), _node("vid", "video_gen", prompt="没有参考")])
        answer = self.run_nodes(["img", "vid"], saved["version"])
        self.assertEqual(answer["status"], "blocked")
        rows = {row["node_id"]: row for row in answer["assessment"]["nodes"]}
        self.assertEqual(rows["vid"]["problems"][0]["code"], "no_reference")
        self.assertEqual(rows["img"]["problems"][0]["code"], "generation_batch_admission_withheld")
        self.assertEqual((self.gateway.image_calls, self.gateway.video_calls), ([], []))

    def test_notes_cannot_be_run_and_a_stale_canvas_cannot_spend(self):
        saved = self.put([_node("n", "note", text="x"), _node("img", "image_gen", prompt="好")])
        self.assertEqual(self.run_nodes(["n"], saved["version"])["status"], "blocked")
        stale = self.client.post(f"{self.base}/canvas/runs", json={"expected_version": 0, "node_ids": ["img"], "operation_id": "op-9", "confirm": True})
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(self.gateway.image_calls, [])

    def test_the_video_gate_is_the_stage_five_one(self):
        saved = self.put([_node("up", "media", output={"medium": "image", "url": "/media/up.png"}), _node("vid", "video_gen", prompt="走", params={"durationSeconds": 7})], [_edge("up", "vid")])
        with patch("app.core.video_admission.renderable_shot_durations", return_value=[5, 10]):
            pending = self.run_nodes(["vid"], saved["version"], op="op-a")
            self.assertEqual(pending["status"], "needs_confirmation")
            self.assertEqual(pending["assessment"]["decision"], "confirmation_required")
            self.assertEqual(pending["assessment"]["confirmations"][0]["requested_seconds"], 10)
            self.assertEqual(self.gateway.video_calls, [])
            done = self.run_nodes(["vid"], saved["version"], op="op-b", confirmed=[{"scripted_seconds": 7, "requested_seconds": 10}])
            self.assertEqual(done["status"], "started")
        self.assertEqual(self.gateway.video_calls[0]["duration"], 10)
        with patch("app.core.model_gateway.ModelGateway.video_family_ready", return_value=False), patch("app.core.model_gateway.ModelGateway.video_model_problem", return_value="视频模型族 x 没有可用的运行时凭据"):
            refused = self.run_nodes(["vid"], saved["version"], op="op-c")
        self.assertEqual(refused["status"], "blocked")
        self.assertEqual(refused["assessment"]["nodes"][0]["problems"][0]["code"], "provider_not_ready")

    def test_a_batch_runs_upstream_first_and_a_failure_skips_what_depends_on_it(self):
        saved = self.put(
            [_node("img", "image_gen", prompt="首帧"), _node("vid", "video_gen", prompt="动起来")],
            [_edge("img", "vid", "first_frame")],
        )
        self.assertEqual(self.run_nodes(["vid", "img"], saved["version"], op="op-a")["status"], "started")
        self.assertEqual(self.gateway.video_calls[0]["first_frame"], "/media/image_1.png")

        self.gateway.fail_with = "provider exploded"
        self.run_nodes(["vid", "img"], saved["version"], op="op-b")
        latest = self.client.get(f"{self.base}/canvas/outputs").json()["latest"]
        self.assertEqual(latest["img"]["status"], "failed")
        self.assertIn("provider exploded", latest["img"]["error"])
        self.assertEqual(latest["vid"]["status"], "skipped")
        self.assertEqual(len(self.gateway.video_calls), 1)

    def test_a_queued_item_can_be_withdrawn_but_a_running_one_finishes(self):
        saved = self.put([_node("a", "image_gen", prompt="一"), _node("b", "image_gen", prompt="二")], [_edge("a", "b")])
        release, started = threading.Event(), threading.Event()
        real = self.gateway.generate_image

        def slow(*args, **kwargs):
            started.set()
            self.assertTrue(release.wait(10))
            return real(*args, **kwargs)

        self.gateway.generate_image = slow
        self.studio.canvas_runs._spawn = lambda work: threading.Thread(target=work, daemon=True).start()
        answer = self.run_nodes(["a", "b"], saved["version"])
        self.assertTrue(started.wait(10))
        runs = {run["node_id"]: run for run in answer["runs"]}
        batch = answer["batch_id"]
        refused = self.client.post(f"{self.base}/canvas/runs/{batch}/cancel", json={"key": runs["a"]["id"]})
        self.assertEqual(refused.status_code, 422)
        accepted = self.client.post(f"{self.base}/canvas/runs/{batch}/cancel", json={"key": runs["b"]["id"]})
        self.assertEqual(accepted.status_code, 200, accepted.text)
        release.set()
        for _ in range(200):
            latest = self.client.get(f"{self.base}/canvas/outputs").json()["latest"]
            if latest["a"]["status"] == "done" and latest["b"]["status"] == "cancelled":
                break
            threading.Event().wait(0.02)
        self.assertEqual((latest["a"]["status"], latest["b"]["status"]), ("done", "cancelled"))
        self.assertEqual(len(self.gateway.image_calls), 1)

    def test_runs_cut_off_by_a_restart_say_so_instead_of_spinning(self):
        repo = self.studio.repository
        saved = self.put([_node("img", "image_gen", prompt="好")])
        past = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        repo.create_canvas_batch(self.project, "u1", canvas_id="main", task_id="t-1", operation_id="crashed", entries=[{"node_id": "img", "medium": "image"}], lease_expires_at=past)
        latest = self.client.get(f"{self.base}/canvas/outputs").json()["latest"]["img"]
        self.assertEqual(latest["status"], "failed")
        self.assertIn("重启", latest["error"])
        self.assertEqual(self.gateway.image_calls, [])
        self.assertEqual(saved["version"], 1)

    def test_audio_and_compose_use_the_existing_services_and_a_missing_provider_is_said_out_loud(self):
        saved = self.put(
            [
                _node("speech", "audio_gen", prompt="你好"),
                _node("music", "audio_gen", prompt="钢琴", params={"mode": "music"}),
                _node("clip", "media", output={"medium": "video", "url": "/media/c.mp4"}),
                _node("cmp", "video_compose"),
            ],
            [_edge("clip", "cmp", "clip", kind="dependency")],
        )
        with patch.object(media_compositor, "_elevenlabs_available", return_value=False):
            options = self.client.get(f"{self.base}/canvas/run-options").json()
            self.assertFalse(options["kinds"]["audio_gen"]["modes"]["music"])
            self.assertEqual(self.run_nodes(["music"], saved["version"], op="op-a")["status"], "blocked")
        with patch.object(media_compositor, "synthesize_preferred_dialogue_track", return_value=("/media/voice.mp3", "/tmp/voice.mp3")) as tts:
            self.assertEqual(self.run_nodes(["speech"], saved["version"], op="op-b")["status"], "started")
        self.assertEqual(tts.call_args.args[0][0][0], "你好")
        with patch.object(media_compositor, "compose_film", return_value="/media/film.mp4") as compose, patch.object(media_compositor, "_ffmpeg", return_value="ffmpeg"):
            # Local and free: it needs no confirmation.
            self.assertEqual(self.run_nodes(["cmp"], saved["version"], confirm=False, op="op-c")["status"], "started")
        self.assertTrue(compose.call_args.args[0][0].endswith("/c.mp4"))
        self.assertEqual(self.client.get(f"{self.base}/canvas/outputs").json()["outputs"]["cmp"]["url"], "/media/film.mp4")

    def test_results_are_kept_under_media_when_the_provider_hands_back_a_link(self):
        encoded = "data:image/png;base64," + base64.b64encode(_png()).decode("ascii")
        with tempfile.TemporaryDirectory() as media, patch.object(media_compositor, "MEDIA_DIR", media):
            kept = KEEP_MEDIA(encoded, "image", "tag")
            self.assertTrue(os.path.basename(kept["url"]).endswith(".png"))
            self.assertEqual(len(os.listdir(media)), 1)
            with patch.object(media_compositor, "_download", return_value=False):
                lost = KEEP_MEDIA("https://cdn.example/x.mp4?sig=1", "video", "tag")
            self.assertEqual(lost, {"url": "https://cdn.example/x.mp4?sig=1", "remote": True})
            with self.assertRaises(RuntimeError):
                KEEP_MEDIA(None, "video", "tag")

    def test_a_batch_side_by_side_never_garbles_a_paid_result(self):
        # Regression: reads shared one connection across threads, and a finished run was lost to a garbled row.
        saved = self.put([_node(f"n{index}", "image_gen", prompt="好") for index in range(8)])
        for attempt in range(5):
            self.run_nodes([f"n{index}" for index in range(8)], saved["version"], op=f"op-{attempt}")
            latest = self.client.get(f"{self.base}/canvas/outputs").json()["latest"]
            self.assertEqual({item["status"] for item in latest.values()}, {"done"}, latest)


class PrevizTests(CanvasCase):
    def _store_captures(self, captures):
        def mutate(task):
            task["assets"][ASSET_KEY] = {"version": 1, "scenes": {"E1S01": {"captures": captures, "applied": {}}}, "poses": []}

        self.drama.repo.mutate_task("t-1", mutate)

    def test_selected_captures_pull_into_downstream_nodes_as_references(self):
        self._store_captures([
            {"id": "still", "kind": "still", "shot_id": 1, "url": "/media/desk_still.png", "stale": False},
            {"id": "clip", "kind": "clip", "shot_id": 1, "url": "/media/desk_clip.mp4", "stale": False},
            {"id": "other", "kind": "still", "shot_id": 2, "url": "/media/desk_other.png", "stale": False},
        ])
        saved = self.put(
            [_node("pv", "previz", sceneId="E1S01", shotId=1, selectedCaptureIds=["still", "clip"]), _node("vid", "video_gen", prompt="按预演走")],
            [_edge("pv", "vid")],
        )
        self.assertEqual(self.run_nodes(["vid"], saved["version"])["status"], "started")
        call = self.gateway.video_calls[0]
        self.assertEqual((call["ref_images"], call["ref_videos"]), (["/media/desk_still.png"], ["/media/desk_clip.mp4"]))

    def test_a_capture_of_old_blocking_or_a_depth_still_is_refused_the_way_the_desk_refuses_it(self):
        self._store_captures([
            {"id": "old", "kind": "clip", "shot_id": 1, "url": "/media/old.mp4", "stale": True},
            {"id": "depth", "kind": "still", "shot_id": 1, "url": "/media/depth.png", "stale": False, "depth": True},
        ])
        saved = self.put(
            [_node("a", "previz", sceneId="E1S01", shotId=1, selectedCaptureIds=["old"]), _node("b", "previz", sceneId="E1S01", shotId=1, selectedCaptureIds=["depth"]), _node("none", "previz", sceneId="E1S01", shotId=1),
             _node("v1", "video_gen", prompt="走"), _node("v2", "video_gen", prompt="走"), _node("v3", "video_gen", prompt="走")],
            [_edge("a", "v1"), _edge("b", "v2"), _edge("none", "v3")],
        )
        for node_id, expected in (("v1", "旧站位"), ("v2", "深度静帧"), ("v3", "没有选中")):
            answer = self.run_nodes([node_id], saved["version"], op=f"op-{node_id}")
            self.assertEqual(answer["status"], "blocked", node_id)
            self.assertIn(expected, answer["assessment"]["nodes"][0]["problems"][0]["message"])
        self.assertEqual(self.gateway.video_calls, [])


class CommitTests(CanvasCase):
    def _setup_results(self):
        saved = self.put([
            _node("one", "image_gen", prompt="好", binding={"sceneId": "E1S01", "shotId": 1}),
            _node("scene", "video_gen", prompt="走", binding={"sceneId": "E1S01"}),
            _node("loose", "image_gen", prompt="没绑镜头"),
            _node("up", "media", output={"medium": "image", "url": "/media/u.png", "provenance": {"origin": "upload", "filename": "u.png"}}),
            _node("anon", "media", output={"medium": "image", "url": "https://elsewhere/x.png"}),
            _node("empty", "image_gen", prompt="还没跑"),
            _node("txt", "note", text="注释"),
        ], [_edge("up", "scene")])
        answer = self.run_nodes(["one", "scene", "loose"], saved["version"])
        self.assertEqual(answer["status"], "started", answer)
        return saved["version"]

    def test_the_preview_says_how_many_shots_and_what_is_skipped(self):
        self._setup_results()
        preview = self.client.post(f"{self.base}/canvas/commit/preview", json={"node_ids": ["one", "scene", "loose", "up", "anon", "empty", "txt"]}).json()
        rows = {row["node_id"]: row for row in preview["nodes"]}
        self.assertEqual(rows["one"]["impact"]["count"], 1)
        self.assertEqual(rows["scene"]["impact"]["count"], 2)
        self.assertEqual(preview["impacted_shots"], 2)
        self.assertEqual(rows["anon"]["state"], "no_provenance")
        self.assertEqual(rows["up"]["state"], "ready")
        self.assertEqual({rows["empty"]["state"], rows["txt"]["state"]}, {"no_result"})
        self.assertEqual(preview["counts"], {"ready": 4, "no_provenance": 1, "already": 0, "no_result": 2})
        # A preview changes nothing.
        self.assertEqual(self.client.get(f"{self.base}/canvas").json()["version"], 1)
        self.assertFalse(self.drama.repo.get_task("t-1")["assets"]["4"][0].get("sequence_images"))

    def test_a_batch_commit_is_one_canvas_version_and_lands_in_the_shot_slots(self):
        version = self._setup_results()
        outcome = self.client.post(f"{self.base}/canvas/commit", json={"node_ids": ["one", "scene", "anon", "empty"], "expected_version": version}).json()
        self.assertEqual(outcome["counts"], {"committed": 2, "failed": 0, "skipped": 2, "no_provenance": 1})
        self.assertEqual(outcome["version"], version + 1)
        by_id = {node["id"]: node for node in outcome["canvas"]["nodes"]}
        self.assertEqual((by_id["one"]["track"], by_id["scene"]["track"], by_id["anon"]["track"]), ("mainline", "mainline", "freezone"))
        artifact = next(item for item in self.studio.list_artifacts(self.project, "u1") if item["id"] == by_id["one"]["artifact_id"])
        self.assertEqual((artifact["kind"], artifact["payload"]["source"]["kind"]), ("asset", "run"))
        shots = self.drama.repo.get_task("t-1")["assets"]["4"]
        one_url = self.client.get(f"{self.base}/canvas/outputs").json()["outputs"]["one"]["url"]
        self.assertEqual(shots[0]["sequence_images"], [one_url])
        self.assertEqual(shots[0]["reference_videos"], ["/media/video_1.mp4"])
        # In front of what the shot already had, not instead of it.
        self.assertEqual(shots[1]["reference_videos"], ["/media/video_1.mp4", "/media/old.mp4"])
        self.assertNotIn("reference_videos", shots[2])
        # Sending the same thing again does not make a second artifact.
        again = self.client.post(f"{self.base}/canvas/commit", json={"node_ids": ["one"], "expected_version": outcome["version"]}).json()
        self.assertEqual(again["results"][0]["state"], "already")
        self.assertEqual(again["version"], outcome["version"])

    def test_failures_are_reported_and_can_be_retried_alone(self):
        version = self._setup_results()
        real = self.studio.canvas_runs._apply_to_shots
        calls = {"n": 0}

        def flaky(drama, task_id, row):
            calls["n"] += 1
            if row["node_id"] == "one" and calls["n"] == 1:
                raise RuntimeError("存储暂不可用")
            return real(drama, task_id, row)

        with patch.object(self.studio.canvas_runs, "_apply_to_shots", side_effect=flaky):
            outcome = self.client.post(f"{self.base}/canvas/commit", json={"node_ids": ["one", "scene"], "expected_version": version}).json()
            self.assertEqual((outcome["counts"]["committed"], outcome["counts"]["failed"]), (1, 1))
            failed = next(item for item in outcome["results"] if item["status"] == "failed")
            self.assertEqual((failed["node_id"], failed["reason"]), ("one", "存储暂不可用"))
            retried = self.client.post(f"{self.base}/canvas/commit", json={"node_ids": ["one"], "expected_version": outcome["version"]}).json()
        self.assertEqual(retried["counts"]["committed"], 1)
        one_url = self.client.get(f"{self.base}/canvas/outputs").json()["outputs"]["one"]["url"]
        self.assertEqual(self.drama.repo.get_task("t-1")["assets"]["4"][0]["sequence_images"], [one_url])

    def test_a_previz_node_says_which_shot_when_the_result_has_no_binding(self):
        saved = self.put(
            [_node("pv", "previz", sceneId="E1S02", shotId=1), _node("img", "image_gen", prompt="好")],
            [_edge("img", "pv")],
        )
        self.run_nodes(["img"], saved["version"])
        preview = self.client.post(f"{self.base}/canvas/commit/preview", json={"node_ids": ["img"]}).json()
        self.assertEqual(preview["nodes"][0]["impact"]["shots"][0]["scene_id"], "E1S02")

    def test_the_promote_route_commits_a_generated_result_and_still_checks_the_kind(self):
        version = self._setup_results()
        wrong = self.client.post(f"{self.base}/canvas/promote", json={"node_id": "one", "target_kind": "clip", "expected_version": version})
        self.assertEqual(wrong.status_code, 422)
        promoted = self.client.post(f"{self.base}/canvas/promote", json={"node_id": "one", "target_kind": "asset", "expected_version": version})
        self.assertEqual(promoted.status_code, 200, promoted.text)
        node = next(item for item in promoted.json()["nodes"] if item["id"] == "one")
        self.assertEqual(node["track"], "mainline")
        self.assertEqual(self.client.post(f"{self.base}/canvas/commit", json={"node_ids": ["one"], "expected_version": 1}).status_code, 409)
        version = promoted.json()["version"]
        uploaded = self.client.post(f"{self.base}/canvas/promote", json={"node_id": "up", "target_kind": "asset", "expected_version": version})
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        version = uploaded.json()["version"]
        anonymous = self.client.post(f"{self.base}/canvas/promote", json={"node_id": "anon", "target_kind": "asset", "expected_version": version})
        self.assertEqual(anonymous.status_code, 422)
        self.assertEqual(self.client.get(f"{self.base}/canvas").json()["version"], version)


class AgentToolTests(CanvasCase):
    def call(self, name, **arguments):
        with patch("app.api.studio_api.get_studio_service", return_value=self.studio):
            return catalog.call(name, {"task_id": "t-1", **arguments}, service=self.drama, user=self.user)

    def test_the_tools_follow_the_effect_model(self):
        effects = {tool.name: tool.effect for tool in catalog.list()}
        self.assertEqual(
            {name: effects.get(name) for name in ("get_canvas", "edit_canvas", "quote_canvas_run", "run_canvas_nodes")},
            {"get_canvas": "read", "edit_canvas": "write", "quote_canvas_run": "read", "run_canvas_nodes": "paid"},
        )

    def test_a_multi_node_request_is_one_version(self):
        done = self.call("edit_canvas", operations=[
            {"op": "add_node", "ref": "a", "kind": "image_gen", "label": "首帧", "prompt": "雨夜"},
            {"op": "add_node", "ref": "b", "kind": "video_gen", "label": "成片", "prompt": "她走", "params": {"durationSeconds": 6}},
            {"op": "add_node", "ref": "c", "kind": "note", "text": "冷色"},
            {"op": "connect", "source": "a", "target": "b", "role": "first_frame"},
            {"op": "connect", "source": "c", "target": "b"},
            {"op": "group", "ids": ["a", "b"], "label": "第一组"},
        ])
        self.assertTrue(done["ok"], done)
        self.assertEqual(done["result"]["version"], 1)
        versions = self.client.get(f"{self.base}/canvas/versions").json()["versions"]
        self.assertEqual(len(versions), 1)
        canvas = self.client.get(f"{self.base}/canvas").json()
        self.assertEqual({node["kind"] for node in canvas["nodes"]}, {"image_gen", "video_gen", "note", "group"})
        edge = next(item for item in canvas["edges"] if item["payload"]["role"] == "first_frame")
        self.assertEqual(edge["kind"], "reference")
        by_id = {node["id"]: node for node in canvas["nodes"]}
        self.assertLess(by_id[done["result"]["created"]["a"]]["x"], by_id[done["result"]["created"]["b"]]["x"])

        read = self.call("get_canvas")
        self.assertEqual(read["result"]["node_count"], 4)
        self.assertIn("operations", read["result"])

    def test_one_bad_operation_means_nothing_is_applied(self):
        self.call("edit_canvas", operations=[{"op": "add_node", "ref": "n", "kind": "note", "text": "留着"}])
        failed = self.call("edit_canvas", operations=[
            {"op": "add_node", "ref": "a", "kind": "image_gen"},
            {"op": "connect", "source": "a", "target": "还没有这个节点"},
        ])
        self.assertFalse(failed["ok"])
        self.assertIn("整批未生效", failed["error"])
        canvas = self.client.get(f"{self.base}/canvas").json()
        self.assertEqual((canvas["version"], len(canvas["nodes"])), (1, 1))
        for bad in ([{"op": "explode"}], [{"op": "add_node", "kind": "artifact"}], []):
            self.assertFalse(self.call("edit_canvas", operations=bad)["ok"])
        self.assertEqual(self.client.get(f"{self.base}/canvas").json()["version"], 1)

    def test_a_stale_base_version_is_refused(self):
        self.call("edit_canvas", operations=[{"op": "add_node", "kind": "note"}])
        stale = self.call("edit_canvas", operations=[{"op": "add_node", "kind": "note"}], base_version=0)
        self.assertFalse(stale["ok"])
        self.assertIn("别处修改", stale["error"])

    def test_running_waits_for_confirmation_and_goes_through_the_gate(self):
        created = self.call("edit_canvas", operations=[{"op": "add_node", "ref": "a", "kind": "image_gen", "prompt": "雨夜"}])
        node_id = created["result"]["created"]["a"]
        pending = self.call("run_canvas_nodes", node_ids=[node_id])
        self.assertTrue(pending["needs_confirmation"])
        self.assertEqual(self.gateway.image_calls, [])
        quote = self.call("quote_canvas_run", node_ids=[node_id])
        self.assertEqual(quote["result"]["decision"], "admitted")
        started = self.call("run_canvas_nodes", node_ids=[node_id], confirm=True)
        self.assertEqual(started["result"]["status"], "started")
        self.assertEqual(len(self.gateway.image_calls), 1)

    def test_another_persons_task_is_refused(self):
        from app.core.agent_tools import ToolError

        with self.assertRaises(ToolError):
            catalog.call("get_canvas", {"task_id": "t-2"}, service=self.drama, user=self.user)


class RulesTests(unittest.TestCase):
    def test_a_node_output_is_typed_and_a_connection_says_what_it_means(self):
        image = _node("i", "image_gen")
        video = _node("v", "video_gen")
        self.assertEqual(studio_canvas.connection(image, video), ("reference", "ref_image"))
        self.assertEqual(studio_canvas.connection(image, video, role="first_frame"), ("reference", "first_frame"))
        self.assertEqual(studio_canvas.connection(_node("n", "note"), video), ("dependency", "prompt"))
        self.assertEqual(studio_canvas.connection(video, _node("c", "video_compose")), ("dependency", "clip"))
        self.assertEqual(studio_canvas.connection(_node("p", "previz"), video), ("reference", "ref_capture"))
        self.assertEqual(studio_canvas.connection(image, _node("p", "previz")), ("reference", "blockout_image"))
        refusals = [
            (video, image), (image, _node("n", "note")), (_node("g", "group"), video), (_node("m", "media"), video),
            (image, image), (_node("a", "audio_gen"), image),
        ]
        for source, target in refusals:
            with self.assertRaises(studio_canvas.CanvasOperationError):
                studio_canvas.connection(source, target)
        with self.assertRaises(studio_canvas.CanvasOperationError):
            studio_canvas.connection(_node("n", "note"), video, role="first_frame")

    def test_loops_are_found_and_a_looped_batch_cannot_be_ordered(self):
        edges = [{"source": "a", "target": "b"}, {"source": "b", "target": "c"}]
        self.assertTrue(studio_canvas.creates_cycle(edges, "c", "a"))
        self.assertFalse(studio_canvas.creates_cycle(edges, "a", "c"))
        order, upstream = studio_canvas.batch_order(["c", "a", "b"], edges)
        self.assertEqual(order, ["a", "b", "c"])
        self.assertEqual(upstream["c"], ["b"])
        with self.assertRaises(ValueError):
            studio_canvas.batch_order(["a", "b"], [{"source": "a", "target": "b"}, {"source": "b", "target": "a"}])

    def test_only_media_urls_we_can_hand_on_pass(self):
        for good in ("/media/a.png", "https://cdn.example/a.png", "http://localhost:8000/media/a.png", "data:image/png;base64,AAAA"):
            self.assertEqual(studio_canvas.safe_media_url(good), good)
        for bad in ("javascript:alert(1)", "file:///etc/passwd", "ftp://x/y", "https://user:pw@host/x", "", None, "/etc/passwd", "data:text/html,x"):
            self.assertEqual(studio_canvas.safe_media_url(bad), "", bad)

    def test_a_pass_through_node_cannot_recurse_forever_on_a_bad_graph(self):
        a = _node("a", "style_ref")
        b = _node("b", "style_ref")
        nodes = {"a": a, "b": b}
        edges = [{"source": "a", "target": "b"}, {"source": "b", "target": "a"}]
        self.assertIsNone(studio_canvas.effective_output(a, nodes, edges, {}))

    def test_json_payloads_in_the_rules_module_stay_plain(self):
        document = {"nodes": [_node("a", "note")], "edges": []}
        changed, refs = studio_canvas.apply_operations(document, [{"op": "add_node", "ref": "x", "kind": "image_gen", "label": "新"}])
        json.dumps(changed)
        self.assertEqual(len(document["nodes"]), 1, "the input document is left alone")
        self.assertIn("x", refs)


if __name__ == "__main__":
    unittest.main()
