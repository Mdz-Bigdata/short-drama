# -*- coding: utf-8 -*-
"""Seam checks: the same frame reads as joined, a moved subject as suspect, a different picture as a jump."""

import io
import unittest

from PIL import Image, ImageDraw

from app.core import seam_check


def _frame(subject_x=40, brightness=1.0, tint=(0, 0, 0)):
    image = Image.new("RGB", (160, 90), tuple(min(255, int(c * brightness)) for c in (90 + tint[0], 100 + tint[1], 120 + tint[2])))
    ImageDraw.Draw(image).rectangle((subject_x, 20, subject_x + 30, 80), fill=tuple(min(255, int(c * brightness)) for c in (230, 200, 180)))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()


class SeamTests(unittest.TestCase):
    def test_the_same_frame_is_joined(self):
        report = seam_check.compare(_frame(), _frame())
        self.assertEqual(report.verdict, "good")
        self.assertLess(report.score, 0.05)

    def test_a_subject_that_moved_across_the_frame_is_at_least_suspect(self):
        report = seam_check.compare(_frame(subject_x=20), _frame(subject_x=110))
        self.assertIn(report.verdict, {"suspect", "jump"})
        self.assertIn("构图", report.detail)

    def test_a_different_picture_is_a_jump(self):
        other = Image.new("RGB", (160, 90), (10, 10, 10))
        ImageDraw.Draw(other).ellipse((10, 10, 150, 80), fill=(250, 250, 250))
        buffer = io.BytesIO()
        other.save(buffer, format="JPEG")
        self.assertEqual(seam_check.compare(_frame(), buffer.getvalue()).verdict, "jump")

    def test_a_light_change_shows_as_exposure(self):
        report = seam_check.compare(_frame(), _frame(brightness=0.45))
        self.assertGreater(report.exposure, report.structure * 0.5)
        self.assertNotEqual(report.verdict, "good")

    def test_a_small_colour_drift_is_not_a_jump(self):
        self.assertEqual(seam_check.compare(_frame(), _frame(tint=(8, 0, -6))).verdict, "good")

    def test_sizes_may_differ_and_data_uris_are_read(self):
        import base64

        big = Image.open(io.BytesIO(_frame())).resize((320, 180))
        buffer = io.BytesIO()
        big.save(buffer, format="JPEG")
        uri = "data:image/jpeg;base64," + base64.b64encode(_frame()).decode()
        self.assertEqual(seam_check.compare(uri, buffer.getvalue()).verdict, "good")

    def test_the_dict_carries_what_a_person_reads(self):
        report = seam_check.compare(_frame(), _frame()).as_dict()
        self.assertEqual(set(report), {"score", "verdict", "label", "structure", "exposure", "tone", "detail"})
        self.assertEqual(report["label"], "接上了")


if __name__ == "__main__":
    unittest.main()
