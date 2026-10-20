import unittest

from pydantic import ValidationError

from app.schema.drama import DramaConfigSchema, DramaCreateRequest
from app.service.drama_service import DramaService


def _request(**overrides):
    values = {
        "titleSuggestion": "自动选择视频生成方式",
        "videoReferenceMode": "auto",
        "oneClick": False,
        "episodeCount": 3,
    }
    values.update(overrides)
    return DramaCreateRequest.model_validate(values)


class _MemoryRepo:
    def __init__(self):
        self.task = {
            "task_id": "task-1",
            "config": {
                "title_suggestion": "旧标题",
                "director_style": "retro",
                "shot_style": "standard",
                "llm_model": "old-text",
                "image_model": "old-image",
                "video_model": "old-video",
                "tts_model": "old-audio",
                "video_reference_mode": "auto",
                "one_click": False,
                "episode_count": 1,
            },
        }

    def get_task(self, task_id):
        return self.task if task_id == "task-1" else None

    def save_task(self, task_id, task):
        assert task_id == "task-1"
        self.task = task


class DramaVideoReferenceConfigTests(unittest.TestCase):
    def test_new_project_config_rejects_removed_first_frame_mode(self):
        with self.assertRaises(ValidationError):
            _request(videoReferenceMode="first_frame")

    def test_legacy_task_response_can_still_read_first_frame_mode(self):
        config = DramaConfigSchema.model_validate({
            "titleSuggestion": "旧项目",
            "videoReferenceMode": "first_frame",
        })
        self.assertEqual(config.video_reference_mode, "first_frame")

    def test_update_persists_video_strategy_and_project_controls(self):
        service = DramaService.__new__(DramaService)
        service.repo = _MemoryRepo()
        request = _request(
            videoReferenceMode="multimodal",
            oneClick=True,
            episodeCount=6,
        )

        task = service.update_task_config("task-1", request)

        self.assertEqual(task["config"]["video_reference_mode"], "multimodal")
        self.assertTrue(task["config"]["one_click"])
        self.assertEqual(task["config"]["episode_count"], 6)

    def test_long_form_episode_counts_are_accepted_up_to_150(self):
        service = DramaService.__new__(DramaService)
        service.repo = _MemoryRepo()

        task = service.update_task_config("task-1", _request(episodeCount=150))

        self.assertEqual(task["config"]["episode_count"], 150)

    def test_episode_count_beyond_the_ceiling_is_rejected(self):
        with self.assertRaises(ValidationError):
            _request(episodeCount=151)


if __name__ == "__main__":
    unittest.main()
