"""Run from backend: .venv/bin/python -m scripts.benchmark_storyboard_concurrency.

Controlled fake-provider benchmark; no paid API, database, or media writes.
"""

import json
import logging
import statistics
import time
from unittest.mock import patch

from tests.test_storyboard_concurrency import ImageProbe, generate_test_board


def measure(workers):
    durations = []
    calls = []
    peaks = []
    for _ in range(5):
        probe = ImageProbe(delay=0.1)
        with patch.dict("os.environ", {"STORYBOARD_IMAGE_CONCURRENCY": str(workers)}):
            start = time.perf_counter()
            result = generate_test_board(probe)
            durations.append(round((time.perf_counter() - start) * 1000, 2))
        assert len(result["shots"]) == 9
        assert sorted(probe.calls) == list(range(1, 10))
        calls.append(len(probe.calls))
        peaks.append(probe.peak)
    return {
        "workers": workers,
        "milliseconds": durations,
        "median_ms": statistics.median(durations),
        "calls": calls,
        "peak": peaks,
    }


if __name__ == "__main__":
    logging.getLogger().handlers = [logging.NullHandler()]
    print(
        json.dumps({"provider": "fake 100ms/image", "runs": [measure(1), measure(3)]})
    )
