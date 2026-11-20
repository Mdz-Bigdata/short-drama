"""The stage-1 director is told how many episodes a serial has, so it plans for those and not for an imagined 60."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import creation_modes
from app.repository.task_repo import TaskRepository
from app.schema.drama import DramaCreateRequest
from app.service.drama_service import DramaService


class FrameTest(unittest.TestCase):
    def test_a_serial_gets_its_count_and_length(self):
        line = creation_modes.director_frame({"creation_mode": "narration", "episode_count": 12, "episode_target_duration": 60})
        self.assertIn("12 集", line)
        self.assertIn("60 秒", line)

    def test_a_short_film_and_an_advert_get_nothing(self):
        self.assertEqual(creation_modes.director_frame({"creation_mode": "film", "episode_count": 1}), "")
        self.assertEqual(creation_modes.director_frame({"creation_mode": "ad", "episode_count": 1}), "")

    def test_the_directors_request_carries_it(self):
        requests = []

        def model(model_name, system_prompt, user_prompt, *args, **kwargs):
            requests.append(user_prompt)
            return ""

        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"HARNESS_EVOLUTION": "off"}):
            service = DramaService()
            service.repo = TaskRepository(str(Path(temp) / "tasks.json"))
            service.gateway.call_llm = model
            task = service.create_task(DramaCreateRequest(titleSuggestion="一部十二集的剧", episodeCount=12), owner_user_id="u1")
            try:
                service._execute_stage_blocking(task["task_id"], 1)
            except Exception:  # noqa: BLE001 - an empty plan fails the stage; the request is what is checked
                pass
        director = next(request for request in requests if "导演方案定调" in str(request))
        self.assertIn("全剧共 12 集", director)


if __name__ == "__main__":
    unittest.main()
