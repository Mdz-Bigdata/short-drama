import base64
import json
import os
import unittest
from unittest.mock import patch

import httpx

from app.core.providers import video_adapters
from app.core.providers.video_adapters import (
    GrokImagineAdapter,
    HappyHorseFalAdapter,
    KlingVideoAdapter,
    LtxVideoAdapter,
    VideoJobRequest,
    build_video_adapter,
    resolve_family_credentials,
)
from app.platform.runtime_models import RuntimeModelConfiguration, runtime_model_registry


def _jwt_claims(token: str) -> dict:
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


class VideoAdapterTests(unittest.TestCase):
    def test_kling_signs_a_jwt_per_request_and_maps_first_last_frame_then_polls(self):
        calls: list[tuple[str, str, str, bytes]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append((request.method, request.url.path, request.headers.get("authorization", ""), request.content))
            if request.method == "POST":
                return httpx.Response(200, json={
                    "code": 0, "message": "Success", "request_id": "req_1",
                    "data": {"task_id": "task_1", "task_status": "submitted"},
                })
            return httpx.Response(200, json={
                "code": 0, "data": {
                    "task_id": "task_1", "task_status": "succeed",
                    "task_result": {"videos": [{"id": "v1", "url": "https://cdn.example/kling.mp4", "duration": "10"}]},
                },
            })

        adapter = KlingVideoAdapter(
            api_key="ak_test:sk_test", base_url="https://api-singapore.klingai.com",
            transport=httpx.MockTransport(handler),
        )
        try:
            created = adapter.create_video(VideoJobRequest(
                model="kling-v2-1", prompt="雨夜追逐",
                first_frame="https://cdn.example/first.png", last_frame="https://cdn.example/last.png",
                duration_seconds=6,
            ))
            waited = adapter.wait_for_video(created.task_id, timeout_seconds=5, poll_interval_seconds=0)
        finally:
            adapter.close()

        self.assertEqual(created.task_id, "task_1")
        self.assertEqual(waited.video_url, "https://cdn.example/kling.mp4")
        method, path, auth, body = calls[0]
        self.assertEqual((method, path), ("POST", "/v1/videos/image2video"))
        claims = _jwt_claims(auth.removeprefix("Bearer "))
        self.assertEqual(claims["iss"], "ak_test")
        self.assertEqual(claims["exp"] - claims["nbf"], 1805)
        payload = json.loads(body)
        self.assertEqual(payload["model_name"], "kling-v2-1")
        self.assertEqual(payload["image"], "https://cdn.example/first.png")
        self.assertEqual(payload["image_tail"], "https://cdn.example/last.png")
        self.assertEqual(payload["duration"], "10")
        self.assertEqual(payload["mode"], "std")
        self.assertEqual(calls[1][:2], ("GET", "/v1/videos/image2video/task_1"))
        self.assertTrue(calls[1][2].startswith("Bearer "))

    def test_kling_multi_image_uses_image_list_and_refuses_multimodal_before_any_call(self):
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            return httpx.Response(200, json={"code": 0, "data": {"task_id": "task_2", "task_status": "submitted"}})

        adapter = KlingVideoAdapter(api_key="ak:sk", transport=httpx.MockTransport(handler))
        try:
            with self.assertRaisesRegex(RuntimeError, "cannot execute mode multimodal"):
                adapter.create_video(VideoJobRequest(
                    prompt="x", first_frame="https://cdn.example/a.png", reference_videos=["https://cdn.example/m.mp4"],
                ))
            self.assertEqual(calls, [])
            adapter.create_video(VideoJobRequest(
                model="Kling", prompt="x", first_frame="https://cdn.example/a.png",
                reference_images=["https://cdn.example/b.png", "https://cdn.example/a.png", "https://cdn.example/c.png"],
            ))
            self.assertEqual(adapter._task_path, "/v1/videos/multi-image2video")
        finally:
            adapter.close()
        self.assertEqual(calls, ["/v1/videos/multi-image2video"])

        with self.assertRaisesRegex(RuntimeError, "ACCESS_KEY:SECRET_KEY"):
            KlingVideoAdapter(api_key="only-one-part")

    def test_grok_pins_frames_or_references_and_reports_terminal_status(self):
        seen: list[dict] = []
        statuses = iter(["pending", "done"])

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "POST":
                seen.append(json.loads(request.content))
                return httpx.Response(200, json={"request_id": "req_9", "status": "pending"})
            status = next(statuses)
            body = {"request_id": "req_9", "status": status}
            if status == "done":
                body["video"] = {"url": "https://cdn.example/grok.mp4"}
            return httpx.Response(200, json=body)

        adapter = GrokImagineAdapter(api_key="xai-key", transport=httpx.MockTransport(handler))
        try:
            created = adapter.create_video(VideoJobRequest(
                model="Grok", prompt="x", first_frame="https://cdn.example/a.png",
                last_frame="https://cdn.example/z.png", duration_seconds=20,
            ))
            waited = adapter.wait_for_video(created.task_id, timeout_seconds=5, poll_interval_seconds=0)
            adapter.create_video(VideoJobRequest(
                prompt="x", first_frame="https://cdn.example/a.png",
                reference_images=[f"https://cdn.example/{index}.png" for index in range(5)],
            ))
        finally:
            adapter.close()

        self.assertEqual(waited.video_url, "https://cdn.example/grok.mp4")
        first, second = seen
        self.assertEqual(first["model"], "grok-imagine-video-1.5")
        self.assertEqual(first["image"], {"url": "https://cdn.example/a.png"})
        self.assertEqual(first["last_frame"], {"url": "https://cdn.example/z.png"})
        self.assertEqual(first["duration"], 15)
        self.assertNotIn("reference_images", first)
        self.assertEqual(len(second["reference_images"]), 3)
        self.assertEqual(second["reference_images"][0], {"url": "https://cdn.example/a.png"})
        self.assertNotIn("image", second)

        expired = GrokImagineAdapter(
            api_key="xai-key",
            transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"request_id": "r", "status": "expired"})),
        )
        try:
            with self.assertRaisesRegex(RuntimeError, "status=expired"):
                expired.wait_for_video("r", timeout_seconds=5, poll_interval_seconds=0)
        finally:
            expired.close()

    def test_happyhorse_uses_the_fal_queue_protocol_per_mode(self):
        calls: list[tuple[str, str, str]] = []
        polls = iter(["IN_QUEUE", "IN_PROGRESS", "COMPLETED"])

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append((request.method, request.url.path, request.headers.get("authorization", "")))
            if request.method == "POST":
                return httpx.Response(200, json={
                    "request_id": "fal_1",
                    "status_url": "https://queue.fal.run/alibaba/happy-horse/v1.1/reference-to-video/requests/fal_1/status",
                    "response_url": "https://queue.fal.run/alibaba/happy-horse/v1.1/reference-to-video/requests/fal_1",
                })
            if request.url.path.endswith("/status"):
                return httpx.Response(200, json={"status": next(polls)})
            return httpx.Response(200, json={"video": {"url": "https://cdn.example/horse.mp4"}, "seed": 7})

        adapter = HappyHorseFalAdapter(api_key="fal-test", transport=httpx.MockTransport(handler))
        try:
            created = adapter.create_video(VideoJobRequest(
                prompt="x", first_frame="https://cdn.example/a.png",
                reference_images=["https://cdn.example/b.png"], duration_seconds=2, resolution="720p",
            ))
            waited = adapter.wait_for_video(created.task_id, timeout_seconds=5, poll_interval_seconds=0)
            with self.assertRaisesRegex(RuntimeError, "cannot execute mode first_last_frame"):
                adapter.create_video(VideoJobRequest(
                    prompt="x", first_frame="https://cdn.example/a.png", last_frame="https://cdn.example/z.png",
                ))
        finally:
            adapter.close()

        self.assertEqual(waited.video_url, "https://cdn.example/horse.mp4")
        self.assertEqual(calls[0][1], "/alibaba/happy-horse/v1.1/reference-to-video")
        self.assertEqual(calls[0][2], "Key fal-test")
        self.assertEqual([path for _, path, _ in calls[1:4]], [
            "/alibaba/happy-horse/v1.1/reference-to-video/requests/fal_1/status"
        ] * 3)
        self.assertEqual(calls[4][1], "/alibaba/happy-horse/v1.1/reference-to-video/requests/fal_1")

        payload = HappyHorseFalAdapter._payload(adapter, VideoJobRequest(
            prompt="x", first_frame="https://cdn.example/a.png", duration_seconds=2, resolution="720p",
        ), "first_frame")
        self.assertEqual(payload, {
            "prompt": "x", "duration": "3", "resolution": "720p", "aspect_ratio": "9:16",
            "image_url": "https://cdn.example/a.png",
        })

    def test_ltx_maps_resolution_snaps_duration_and_polls_the_v2_job(self):
        seen: list[tuple[str, str, bytes]] = []
        polls = iter(["pending", "processing", "completed"])

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append((request.method, request.url.path, request.content))
            if request.method == "POST":
                return httpx.Response(202, json={"id": "job_1", "status": "pending"})
            status = next(polls)
            body = {"id": "job_1", "status": status}
            if status == "completed":
                body["result"] = {"video_url": "https://cdn.example/ltx.mp4"}
            return httpx.Response(200, json=body)

        adapter = LtxVideoAdapter(api_key="ltx-key", transport=httpx.MockTransport(handler))
        try:
            created = adapter.create_video(VideoJobRequest(
                model="ltx-2-3-pro", prompt="x", first_frame="https://cdn.example/a.png",
                last_frame="https://cdn.example/z.png", duration_seconds=7,
            ))
            waited = adapter.wait_for_video(created.task_id, timeout_seconds=5, poll_interval_seconds=0)
        finally:
            adapter.close()

        self.assertEqual(waited.video_url, "https://cdn.example/ltx.mp4")
        self.assertEqual(seen[0][:2], ("POST", "/v2/image-to-video"))
        payload = json.loads(seen[0][2])
        self.assertEqual(payload["image_uri"], "https://cdn.example/a.png")
        self.assertEqual(payload["last_frame_uri"], "https://cdn.example/z.png")
        self.assertEqual(payload["duration"], 8)
        self.assertEqual(payload["resolution"], "1080x1920")
        self.assertTrue(payload["generate_audio"])
        self.assertEqual(seen[-1][:2], ("GET", "/v2/image-to-video/job_1"))
        self.assertEqual(LtxVideoAdapter.duration_for("ltx-2-3-fast", 15), 16)
        self.assertEqual(LtxVideoAdapter.duration_for("ltx-2-3-fast", 9), 10)
        self.assertEqual(LtxVideoAdapter.duration_for("ltx-2-3-pro", 15), 10)
        self.assertEqual(LtxVideoAdapter.resolution_for("720p", "16:9"), "1280x720")

    def test_family_credentials_resolve_from_the_registry_then_the_environment(self):
        snapshot = runtime_model_registry.list("video")
        try:
            runtime_model_registry.replace([RuntimeModelConfiguration(
                configuration_id="cfg-xai", category="video", provider="xai",
                base_url="https://api.x.ai", api_key="registry-key", model_ids=("grok-imagine-video-1.5",),
            )])
            self.assertEqual(
                resolve_family_credentials("grok", "grok-imagine-video-1.5"),
                ("registry-key", "https://api.x.ai"),
            )
            self.assertEqual(resolve_family_credentials("grok", "Grok Imagine")[0], "registry-key")
            with patch.dict(os.environ, {"LTX_API_KEY": "YOUR_LTX_API_KEY"}, clear=False):
                self.assertIsNone(resolve_family_credentials("ltx_2_3", "ltx-2-3-pro"))
            with patch.dict(os.environ, {"LTX_API_KEY": "env-key", "LTX_BASE_URL": ""}, clear=False):
                self.assertEqual(resolve_family_credentials("ltx_2_3", "ltx-2-3-pro"), ("env-key", "https://api.ltx.io"))
                self.assertTrue(video_adapters.family_ready("ltx_2_3"))
            self.assertIsNone(resolve_family_credentials("seedance", "seedance-2.5"))
        finally:
            runtime_model_registry.replace(list(snapshot))

        adapter = build_video_adapter("happyhorse", api_key="fal-key")
        try:
            self.assertEqual(adapter.base_url, "https://queue.fal.run")
        finally:
            adapter.close()
        with self.assertRaises(RuntimeError):
            build_video_adapter("seedance", api_key="x")


if __name__ == "__main__":
    unittest.main()
