"""Episodes written side by side store exactly what the serial loop stores, in a fraction of the time."""

import json
import threading
import time
import unittest

from app.core.screenwriting.engine import ScreenwritingEngine, ScreenwritingError
from tests.test_screenwriting_engine import MINIATURE_EPISODES, FakeModel


class SlowModel(FakeModel):
    """The fake model with a fixed latency per call, counting how many calls overlap."""

    def __init__(self, delay: float = 0.03):
        super().__init__()
        self.delay = delay
        self._lock = threading.Lock()
        self.in_flight = 0
        self.peak = 0

        self.timeline: list[dict] = []

    @staticmethod
    def _kind(user_prompt: str) -> str:
        if "提炼项目概述" in user_prompt:
            return "overview"
        if "角色与世界观分析师" in user_prompt:
            return "inventory"
        if "分集大纲" in user_prompt or "end_anchor" in user_prompt:
            return "ledger"
        return "episode"

    def __call__(self, system_prompt, user_prompt, max_tokens):
        with self._lock:
            self.in_flight += 1
            self.peak = max(self.peak, self.in_flight)
            overlap = self.in_flight > 1
        try:
            time.sleep(self.delay)
            return super().__call__(system_prompt, user_prompt, max_tokens)
        finally:
            with self._lock:
                self.in_flight -= 1
                self.timeline.append({"kind": self._kind(user_prompt), "overlap": overlap})


def _engine(model, concurrency: int, progress=None) -> ScreenwritingEngine:
    return ScreenwritingEngine(
        model, video_model="seedance2.0", attempts=3, system_prompt="SYS", style="写实电影感",
        episode_shape=MINIATURE_EPISODES, episode_concurrency=concurrency, progress=progress,
    )


def _stored(state):
    keep = ("plan", "script", "prose", "violations", "needs_replan")
    return {key: {field: entry.get(field) for field in keep} for key, entry in state["episodes"].items()}


class ConcurrentEpisodesTests(unittest.TestCase):
    def test_parallel_writing_stores_what_serial_writing_stores(self):
        serial = _engine(FakeModel(), 1).write(title="暗室回声", director_plan="大纲", episode_count=4)
        parallel = _engine(FakeModel(), 3).write(title="暗室回声", director_plan="大纲", episode_count=4)

        self.assertEqual(sorted(parallel["episodes"]), ["1", "2", "3", "4"])
        self.assertEqual(_stored(parallel), _stored(serial))
        self.assertEqual(parallel["inventory"], serial["inventory"])
        self.assertEqual([e["ledger_status"] for e in parallel["ledger"]], ["written"] * 4)

    def test_each_episode_still_opens_on_the_previous_ones_ending(self):
        """Prose is told side by side, so an episode opens on the previous plan's last shots, lines verbatim."""
        model = FakeModel()
        state = _engine(model, 3).write(title="暗室回声", director_plan="大纲", episode_count=3)
        for episode in (2, 3):
            previous_scenes = state["episodes"][str(episode - 1)]["plan"]["scenes"]
            last_line = previous_scenes[-1]["utterances"][-1]["text"]
            prose_prompt = next(c["prompt"] for c in model.calls if "小说体剧本正文" in c["prompt"] and f"下方是第 {episode} 集" in c["prompt"])
            self.assertIn("上一集结尾的分镜内容", prose_prompt)
            self.assertIn(f"“{last_line}”", prose_prompt, f"episode {episode} sees the last line of episode {episode - 1}")

    def test_the_chained_option_opens_on_the_previous_prose_instead(self):
        model = FakeModel()
        engine = _engine(model, 3)
        engine.prose_chain = True
        state = engine.write(title="暗室回声", director_plan="大纲", episode_count=3)
        for episode in (2, 3):
            previous = state["episodes"][str(episode - 1)]["prose"]
            prose_prompt = next(c["prompt"] for c in model.calls if "小说体剧本正文" in c["prompt"] and f"下方是第 {episode} 集" in c["prompt"])
            self.assertIn(previous[-40:], prose_prompt, f"episode {episode} sees the end of episode {episode - 1}")
            self.assertIn("上一集正文的结尾", prose_prompt)

    def test_an_appended_episode_opens_on_the_prose_already_written(self):
        model = FakeModel()
        engine = _engine(model, 3)
        state = engine.write(title="暗室回声", director_plan="大纲", episode_count=2)
        model.calls.clear()
        grown = engine.write_missing(state, [3, 4])
        prompt_3 = next(c["prompt"] for c in model.calls if "小说体剧本正文" in c["prompt"] and "下方是第 3 集" in c["prompt"])
        prompt_4 = next(c["prompt"] for c in model.calls if "小说体剧本正文" in c["prompt"] and "下方是第 4 集" in c["prompt"])
        self.assertIn(state["episodes"]["2"]["prose"][-40:], prompt_3, "episode 3 opens on episode 2's finished prose")
        self.assertIn("上一集结尾的分镜内容", prompt_4, "episode 4 is told beside episode 3, so it opens on its plan")
        self.assertEqual(sorted(grown["episodes"]), ["1", "2", "3", "4"])

    def test_prose_no_longer_waits_for_the_previous_episodes_prose(self):
        # Six episodes, six lanes: the chain tells six proses one after another, the
        # default tells them beside the visual layers in two rounds.
        chained, parallel = SlowModel(), SlowModel()
        engine = _engine(chained, 6)
        engine.prose_chain = True
        started = time.monotonic()
        engine.write(title="暗室回声", director_plan="大纲", episode_count=6)
        chained_seconds = time.monotonic() - started
        started = time.monotonic()
        _engine(parallel, 6).write(title="暗室回声", director_plan="大纲", episode_count=6)
        parallel_seconds = time.monotonic() - started
        self.assertLess(parallel_seconds, chained_seconds * 0.8)

    def test_the_inventory_is_extracted_beside_the_ledger_planning(self):
        model = SlowModel()
        _engine(model, 2).write(title="暗室回声", director_plan="大纲", episode_count=2)
        overlapping = [call["overlap"] for call in model.timeline if call["kind"] in ("inventory", "ledger")]
        self.assertTrue(any(overlapping), "the inventory call and the ledger call ran at the same time")
        serial = SlowModel()
        _engine(serial, 1).write(title="暗室回声", director_plan="大纲", episode_count=2)
        self.assertEqual(serial.peak, 1)

    def test_calls_overlap_and_the_wall_clock_shrinks(self):
        slow_serial, slow_parallel = SlowModel(), SlowModel()
        started = time.monotonic()
        _engine(slow_serial, 1).write(title="暗室回声", director_plan="大纲", episode_count=4)
        serial_seconds = time.monotonic() - started
        started = time.monotonic()
        _engine(slow_parallel, 4).write(title="暗室回声", director_plan="大纲", episode_count=4)
        parallel_seconds = time.monotonic() - started

        self.assertEqual(slow_serial.peak, 1)
        self.assertGreater(slow_parallel.peak, 1)
        self.assertLess(parallel_seconds, serial_seconds * 0.75)

    def test_progress_only_moves_forward(self):
        seen: list[int] = []
        _engine(SlowModel(0.005), 3, progress=lambda percent, label: seen.append(percent)).write(
            title="暗室回声", director_plan="大纲", episode_count=3,
        )
        self.assertEqual(seen, sorted(seen))
        self.assertGreaterEqual(seen[-1], 80)

    def test_an_episode_that_cannot_be_planned_fails_the_whole_run(self):
        model = FakeModel()
        model.plan_overrides[2] = lambda attempt, prompt: json.dumps({"title": "坏", "scenes": []}, ensure_ascii=False)
        with self.assertRaisesRegex(ScreenwritingError, "第 2 集"):
            _engine(model, 3).write(title="暗室回声", director_plan="大纲", episode_count=3)


if __name__ == "__main__":
    unittest.main()
