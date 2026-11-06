import os
import tempfile
import time
import unittest
from unittest.mock import patch

from app.core import media_compositor, video_admission


class MediaAvailableTests(unittest.TestCase):
    def test_an_expired_signed_link_is_gone_and_a_live_one_is_not(self):
        past, future = int(time.time()) - 60, int(time.time()) + 3600
        self.assertFalse(media_compositor.media_available(f"https://x.oss-cn-shanghai.aliyuncs.com/a.mp4?Expires={past}&Signature=s"))
        self.assertTrue(media_compositor.media_available(f"https://x.oss-cn-shanghai.aliyuncs.com/a.mp4?Expires={future}&Signature=s"))
        self.assertFalse(media_compositor.media_available(
            "https://b.s3.amazonaws.com/a.mp4?X-Amz-Date=20200101T000000Z&X-Amz-Expires=3600"))
        self.assertTrue(media_compositor.media_available("https://cdn.example.com/a.mp4"))
        self.assertFalse(media_compositor.media_available(""))

    def test_a_local_media_url_needs_its_file(self):
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, "clip.mp4"), "wb") as handle:
                handle.write(b"0" * 2048)
            with patch.object(media_compositor, "MEDIA_DIR", root):
                self.assertTrue(media_compositor.media_available("http://localhost:8000/media/clip.mp4"))
                self.assertFalse(media_compositor.media_available("http://localhost:8000/media/gone.mp4"))

    def test_an_expired_clip_is_not_quoted_as_reuse(self):
        past = int(time.time()) - 60
        self.assertFalse(video_admission._clip_reusable({"video_url": f"https://x.aliyuncs.com/a.mp4?Expires={past}"}))
        self.assertTrue(video_admission._clip_reusable({"video_url": "https://cdn.example.com/a.mp4"}))
        self.assertFalse(video_admission._clip_reusable({"video_url": "https://cdn.example.com/a.mp4", "stale": True}))


if __name__ == "__main__":
    unittest.main()
