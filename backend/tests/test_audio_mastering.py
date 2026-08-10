import unittest

from app.core.media_compositor import _append_master_mix_filters


class AudioMasteringFilterTests(unittest.TestCase):
    def test_final_compositor_ducks_bgm_under_dialogue_and_limits_master(self):
        filters = ["[1:a]anull[v1]", "[2:a]anull[bgm]", "[3:a]anull[sfx]"]
        output = _append_master_mix_filters(filters, ["[v1]"], "[bgm]", "[sfx]")
        graph = ";".join(filters)

        self.assertEqual(output, "[aout]")
        self.assertIn("sidechaincompress", graph)
        self.assertIn("loudnorm=I=-16", graph)
        self.assertIn("alimiter", graph)


if __name__ == "__main__":
    unittest.main()
