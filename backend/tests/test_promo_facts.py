import unittest

from app.core import promo_facts
from app.service.drama_service import parse_pr_info


def _task(films=(1,)):
    scenes = [{"utterances": [
        {"kind": "dialogue", "speaker": "裴仲玄", "text": "贱籍碰剑，断手。"},
        {"kind": "action", "text": "雨声"},
        {"kind": "dialogue", "speaker": "苏问剑", "text": "伸手。"},
        {"kind": "dialogue", "speaker": "苏问剑", "text": "伸手。"},
    ]}]
    episodes = {
        str(n): {"film": {"final_video_url": f"http://x/film_e{n}.mp4"},
                 "timeline": {"clips": [{"duration": 60.0, "included": True}]}}
        for n in films
    }
    return {"assets": {
        "2_screenwriting": {"episodes": [
            {"episode": 1, "plan": {"title": "第1集 贱籍碰剑，断手", "scenes": scenes}},
            {"episode": 2, "plan": {"title": "第2集 你这双手", "scenes": []}},
        ]},
        "episode_cycle": {"version": 1, "episodes": episodes},
    }}


class ProductionFactsTests(unittest.TestCase):
    def test_lists_every_episode_with_its_film_state_and_real_lines(self):
        facts = promo_facts.production_facts(_task())
        self.assertIn("本剧已写定 2 集，其中 1 集成片已合成", facts)
        self.assertIn("第1集「贱籍碰剑，断手」：成片已合成", facts)
        self.assertIn("第2集「你这双手」：成片未合成", facts)
        self.assertIn("裴仲玄：「贱籍碰剑，断手。」", facts)
        self.assertEqual(facts.count("伸手"), 1)
        self.assertNotIn("雨声", facts)

    def test_is_empty_without_a_screenplay(self):
        self.assertEqual(promo_facts.production_facts({"assets": {}}), "")


class LabelledPickTests(unittest.TestCase):
    def test_takes_the_last_labelled_pair(self):
        text = (
            "## 方案\n> 语言：中文 ｜ 平台主阵地：抖音\n正文提到【封面大字标题】要醒目。\n\n"
            "【封面大字标题】贱籍碰剑，断手\n【黄金引流文案】「贱籍碰剑，断手。」他跪着擦完那把剑，只说了一句：布脏了。\n"
        )
        self.assertEqual(
            promo_facts.labelled_pick(text),
            ("贱籍碰剑，断手", "「贱籍碰剑，断手。」他跪着擦完那把剑，只说了一句：布脏了。"),
        )

    def test_a_quote_wrapping_the_whole_line_is_dropped(self):
        text = "【封面大字标题】「贱籍碰剑，断手」\n【黄金引流文案】“他只回一句：布脏了，我换一块。”\n"
        self.assertEqual(promo_facts.labelled_pick(text), ("贱籍碰剑，断手", "他只回一句：布脏了，我换一块。"))

    def test_missing_labels_give_empty_strings(self):
        self.assertEqual(promo_facts.labelled_pick("没有约定格式的方案"), ("", ""))

    def test_fallback_parser_skips_meta_lines(self):
        text = "# 方案\n> 语言：中文 ｜ 平台主阵地：抖音 ｜ 画幅基准：竖屏九比十六三十帧\n他跪在雨里擦剑，盟主一脚踩住他的手背，满场哄笑无人敢言。\n"
        _, body = parse_pr_info(text, "拭剑奴", "默认")
        self.assertTrue(body.startswith("他跪在雨里擦剑"))


if __name__ == "__main__":
    unittest.main()
