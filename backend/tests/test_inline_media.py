import base64
import tempfile
import unittest
from pathlib import Path

from app.core.inline_media import marker, strip_stage_five_routes, without_inline_media
from app.repository.task_repo import TaskRepository

PICTURE = "data:image/png;base64," + base64.b64encode(b"\x89PNG" + b"0" * 4096).decode("ascii")


def _task(task_id="inline-1"):
    return {
        "task_id": task_id,
        "status": "idle",
        "config": {},
        "logs": {},
        "assets": {"5": [
            {"shot_uid": 1, "video_url": "/media/a.mp4", "video_route_decision": {
                "mode": "multi_reference",
                "first_frame": "https://cdn.test/frame.png",
                "reference_images": ["https://cdn.test/sheet.png", PICTURE],
            }},
            {"shot_uid": 2, "video_url": "/media/b.mp4", "video_route_decision": {"mode": "first_frame"}},
        ]},
    }


class InlineMediaTests(unittest.TestCase):
    def test_a_picture_becomes_a_marker_in_the_same_position(self):
        cleaned = without_inline_media(_task()["assets"]["5"][0]["video_route_decision"])

        self.assertEqual(cleaned["reference_images"][0], "https://cdn.test/sheet.png")
        self.assertEqual(cleaned["reference_images"][1], marker(PICTURE))
        self.assertTrue(cleaned["reference_images"][1].startswith("inline:image/png "))
        self.assertTrue(cleaned["reference_images"][1].endswith("KB"))

    def test_a_clean_record_is_returned_as_is(self):
        route = {"mode": "first_frame", "reference_images": ["https://cdn.test/a.png"]}

        self.assertIs(without_inline_media(route), route)

    def test_stage_five_routes_are_stripped_in_place(self):
        task = _task()

        self.assertTrue(strip_stage_five_routes(task))
        self.assertFalse(strip_stage_five_routes(task), "a second pass finds nothing")
        self.assertNotIn("data:", str(task))


class RepositoryWriteTests(unittest.TestCase):
    """An in-memory copy from before the rule cannot write the bytes back."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))

    def tearDown(self):
        self.temp.cleanup()

    def test_save_and_mutate_never_store_inline_pictures(self):
        self.repo.save_task("inline-1", _task())
        self.assertNotIn("data:", str(self.repo.get_task("inline-1")))

        def put_back(task):
            task["assets"]["5"][1]["video_route_decision"]["reference_images"] = [PICTURE]
            return True

        self.repo.mutate_task("inline-1", put_back)
        stored = self.repo.get_task("inline-1")
        self.assertNotIn("data:", str(stored))
        self.assertTrue(stored["assets"]["5"][1]["video_route_decision"]["reference_images"][0].startswith("inline:"))


if __name__ == "__main__":
    unittest.main()
