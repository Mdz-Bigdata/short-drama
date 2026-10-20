"""No-network regressions for bounded, ordered storyboard image work."""

import re
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

from app.core.model_gateway import ModelGateway
from app.service.drama_service import DramaService


def generate_test_board(generate_image, *, preflight=None, compose=None):
    """Exercise the production pipeline without database, network or media writes."""
    service = DramaService.__new__(DramaService)
    service.gateway = ModelGateway.__new__(ModelGateway)
    task = {
        "task_id": "synthetic-storyboard",
        "assets": {
            "3_sheets": {"林夏": "https://image.test/lin.png"},
            "3_characters": [{"name": "林夏", "desc": "青灰大衣"}],
        },
        "config": {"llm_model": "m", "image_model": "img", "video_model": "v"},
    }
    scene = {
        "scene_id": "E1S02",
        "content": "林夏追查线索",
        "characters": ["林夏"],
        "duration": "45s",
    }
    table = "\n".join(
        f"| {i} | MS | 平视 | Fixed | 林夏翻开档案第{i}页 | | 环境声 | 2s | 线索 | 林夏 | E1S02 办公室 |"
        for i in range(1, 10)
    )
    with patch.object(service.gateway, "call_llm", return_value=table), patch.object(
        service.gateway, "generate_image", side_effect=generate_image
    ), patch(
        "app.service.drama_service.load_storyboard_elements", return_value=[]
    ), patch(
        "app.service.drama_service.compose_nine_grid",
        side_effect=compose or (lambda images, path: path),
    ), patch.object(
        service.gateway, "validate_image_request", side_effect=preflight, create=True
    ):
        return service._generate_scene_board(
            task,
            task["config"],
            scene,
            sys_prompt="s",
            storyboard_negative="",
            title="十二小时",
            genre="mystery",
            dir_style="noir",
            shot_style="cinematic",
            guidance="",
            char_info=("林夏", "记者", "周教授", "反派"),
        )


class ImageProbe:
    def __init__(self, delay=0.01, fail=()):
        self.delay = delay
        self.fail = fail
        self.lock = threading.Lock()
        self.active = self.peak = 0
        self.calls = []

    def __call__(self, model, prompt, ref_images=None, **kwargs):
        number = int(re.search(r"档案第(\d+)页", prompt)[1])
        with self.lock:
            self.calls.append(number)
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            time.sleep(self.delay)
            if number in self.fail:
                raise RuntimeError("synthetic provider failure")
            return f"https://image.test/{number}.png", "fake"
        finally:
            with self.lock:
                self.active -= 1


class StoryboardConcurrencyTests(unittest.TestCase):
    def test_default_runs_three_images_at_once_and_keeps_nine_ordered_results(self):
        probe = ImageProbe()
        with patch.dict("os.environ", {"STORYBOARD_IMAGE_CONCURRENCY": "3"}):
            result = generate_test_board(probe)
        self.assertEqual(probe.peak, 3)
        self.assertEqual(sorted(probe.calls), list(range(1, 10)))
        self.assertEqual(
            [shot["image_url"] for shot in result["shots"]],
            [f"https://image.test/{i}.png" for i in range(1, 10)],
        )

    def test_one_worker_is_a_serial_rollback_with_identical_output(self):
        probe = ImageProbe()
        with patch.dict("os.environ", {"STORYBOARD_IMAGE_CONCURRENCY": "1"}):
            result = generate_test_board(probe)
        self.assertEqual(probe.peak, 1)
        self.assertEqual(probe.calls, list(range(1, 10)))
        self.assertEqual(len(result["shots"]), 9)

    def test_two_boards_share_a_process_wide_three_image_ceiling(self):
        # Exercise the scheduler directly: patching process-global gateway methods
        # concurrently would make the test fixture, not the product, race.
        from app.core.storyboard_concurrency import map_storyboard_images

        probe = ImageProbe()

        def board(_):
            return map_storyboard_images(
                lambda i: probe("m", f"档案第{i}页"), list(range(1, 10))
            )

        with patch.dict(
            "os.environ", {"STORYBOARD_IMAGE_CONCURRENCY": "3"}
        ), ThreadPoolExecutor(max_workers=2) as callers:
            results = list(callers.map(board, [1, 2]))
        self.assertEqual(probe.peak, 3)
        self.assertEqual(len(probe.calls), 18)
        self.assertEqual([len(result) for result in results], [9, 9])

    def test_preflight_checks_every_panel_before_any_provider_call(self):
        checked = []

        def reject_last(*args, **kwargs):
            checked.append(1)
            if len(checked) == 9:
                raise ValueError("unsupported reference model")

        probe = ImageProbe()
        with self.assertRaisesRegex(ValueError, "unsupported reference"):
            generate_test_board(probe, preflight=reject_last)
        self.assertEqual(probe.calls, [])

    def test_failed_panel_never_composes_or_returns_a_done_board(self):
        probe = ImageProbe(fail=(3,))
        with self.assertRaisesRegex(RuntimeError, "分镜图生成不完整"):
            generate_test_board(
                probe, compose=lambda *args: self.fail("failed board must not compose")
            )
        self.assertEqual(sorted(probe.calls), list(range(1, 10)))

    def test_results_stay_ordered_when_first_finishes_after_second(self):
        second_finished = threading.Event()

        def delayed(model, prompt, **kwargs):
            number = int(re.search(r"档案第(\d+)页", prompt)[1])
            if number == 1:
                self.assertTrue(second_finished.wait(2))
            if number == 2:
                second_finished.set()
            return f"https://image.test/{number}.png", "fake"

        result = generate_test_board(delayed)
        self.assertEqual(
            [shot["image_url"] for shot in result["shots"]],
            [f"https://image.test/{i}.png" for i in range(1, 10)],
        )

    def test_gateway_preflight_rejects_unsupported_identity_reference_without_http(
        self,
    ):
        gateway = ModelGateway.__new__(ModelGateway)
        runtime = SimpleNamespace(provider="gemini", model_ids=("img",))
        with patch(
            "app.core.model_gateway.runtime_model_registry.resolve",
            return_value=runtime,
        ), patch.object(
            gateway, "_http_image", side_effect=AssertionError("must not call provider")
        ):
            with self.assertRaisesRegex(ValueError, "参考图"):
                gateway.validate_image_request(
                    "img",
                    ["https://image.test/ref.png"],
                    require_reference_support=True,
                )

    def test_scheduler_clamps_invalid_and_excessive_concurrency(self):
        from app.core.storyboard_concurrency import map_storyboard_images

        for configured, expected in (("0", 1), ("99", 3), ("invalid", 3)):
            with self.subTest(configured=configured), patch.dict(
                "os.environ", {"STORYBOARD_IMAGE_CONCURRENCY": configured}
            ):
                probe = ImageProbe()
                result = map_storyboard_images(
                    lambda i: probe("m", f"档案第{i}页"), list(range(1, 10))
                )
                self.assertEqual(probe.peak, expected)
                self.assertEqual(len(result), 9)

    def test_scheduler_drains_started_calls_after_a_fatal_error(self):
        from app.core.storyboard_concurrency import map_storyboard_images

        probe = ImageProbe(delay=0.02)

        def work(i):
            if i == 1:
                raise ValueError("configuration changed after preflight")
            return probe("m", f"档案第{i}页")

        with self.assertRaisesRegex(ValueError, "configuration changed"):
            map_storyboard_images(work, list(range(1, 10)))
        self.assertEqual(probe.active, 0)
        self.assertLessEqual(len(probe.calls), 2)
        # Failure must not poison or deadlock later scenes using the shared pool.
        self.assertEqual(map_storyboard_images(lambda i: i, [1, 2, 3]), [1, 2, 3])

    def test_scheduler_empty_input_does_not_schedule_work(self):
        from app.core.storyboard_concurrency import map_storyboard_images

        self.assertEqual(
            map_storyboard_images(lambda _: self.fail("unexpected call"), []), []
        )

    def test_finished_slot_is_reused_while_first_panel_is_slow(self):
        from app.core.storyboard_concurrency import map_storyboard_images

        fourth_started = threading.Event()

        def work(i):
            if i == 1 and not fourth_started.wait(0.5):
                raise RuntimeError("completed image slots were left idle")
            if i == 4:
                fourth_started.set()
            return i

        with patch.dict("os.environ", {"STORYBOARD_IMAGE_CONCURRENCY": "3"}):
            self.assertEqual(map_storyboard_images(work, [1, 2, 3, 4]), [1, 2, 3, 4])

    def test_later_fatal_result_stops_submission_before_slow_first_finishes(self):
        from app.core import storyboard_concurrency

        fatal_happened = threading.Event()
        submitted = []
        original_submit = storyboard_concurrency._IMAGE_POOL.submit

        def work(i):
            if i == 3:
                fatal_happened.set()
                raise ValueError("invalid third panel")
            if i < 3:
                fatal_happened.wait(0.5)
                time.sleep(0.02)
            return i

        def record_submit(fn, item):
            submitted.append(item)
            return original_submit(fn, item)

        with patch.dict(
            "os.environ", {"STORYBOARD_IMAGE_CONCURRENCY": "3"}
        ), patch.object(
            storyboard_concurrency._IMAGE_POOL, "submit", side_effect=record_submit
        ), self.assertRaisesRegex(
            ValueError, "invalid third panel"
        ):
            storyboard_concurrency.map_storyboard_images(work, list(range(1, 10)))
        self.assertEqual(submitted, [1, 2, 3])

    def test_breaker_concurrent_failure_updates_are_not_lost(self):
        gateway = ModelGateway.__new__(ModelGateway)
        gateway._host_state_lock = threading.RLock()

        class SlowReadDict(dict):
            def get(self, key, default=None):
                value = super().get(key, default)
                time.sleep(0.001)
                return value

        gateway._host_fail = SlowReadDict()
        gateway._broken_hosts = {}
        gateway._broken_threshold = 2
        gateway._broken_cooldown = 45
        gateway._broken_cooldown_max = 600
        with ThreadPoolExecutor(max_workers=3) as workers:
            list(workers.map(gateway._mark_host_broken, ["https://fake.test/v1"] * 12))
        self.assertEqual(gateway._host_fail["fake.test"], 12)


if __name__ == "__main__":
    unittest.main()
