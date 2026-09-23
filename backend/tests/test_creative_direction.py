# -*- coding: utf-8 -*-
"""Genre routing and feeling decoding: a brief in words, parameters out.

The same words must always decode to the same numbers, a feeling that fights the
main one must be dropped rather than averaged in, and a story with no stated
feeling must still get direction from its genre.
"""

import unittest

from app.core import creative_intent as intent
from app.core import genre_clusters as clusters


class IntentDecodingTests(unittest.TestCase):
    def test_a_brief_decodes_to_the_same_numbers_every_time(self):
        first = intent.decode("这一集要燃一点")
        again = intent.decode("这一集要燃一点")

        self.assertEqual(first.as_dict(), again.as_dict())
        self.assertEqual(first.primary.id, "burning")
        self.assertLess(first.rhythm, 1.0)          # hot-blooded cuts faster than the baseline

    def test_the_first_feeling_named_leads_and_the_rest_only_bend_it(self):
        plan = intent.decode("要压抑一点，带点悬疑")

        self.assertEqual(plan.primary.id, "oppressive")
        self.assertEqual([item.id for item in plan.secondary], ["eerie"])
        # The primary keeps 70% of the weight, so the numbers stay near its own.
        self.assertAlmostEqual(plan.rhythm, 1.5 * 0.7 + 1.2 * 0.3, places=2)
        self.assertGreater(plan.sizes[2], plan.sizes[0])     # close-ups dominate

    def test_a_feeling_that_fights_the_main_one_is_dropped_not_averaged(self):
        plan = intent.decode("", primary="oppressive", secondary=["burning", "eerie"])

        self.assertEqual([item.id for item in plan.secondary], ["eerie"])
        self.assertEqual(len(plan.dropped), 1)
        self.assertIn("相冲", plan.dropped[0][1])
        self.assertIn("已丢弃冲突次感觉", plan.brief())

    def test_at_most_two_secondary_feelings_survive(self):
        plan = intent.decode("", primary="tension", secondary=["epic", "impact", "beat_synced"])

        self.assertEqual(len(plan.secondary), 2)
        self.assertEqual(plan.dropped[0][1], "一份分镜最多两个次感觉")

    def test_an_unreadable_brief_still_gets_direction(self):
        plan = intent.decode("随便写点什么", default="eerie")

        self.assertEqual(plan.primary.id, "eerie")
        self.assertEqual(plan.secondary, [])

    def test_the_brief_states_every_one_of_the_seven_parameters(self):
        text = intent.decode("特效拉满").brief()

        for label in ("运镜倾向", "景别分布", "特效密度", "构图", "光影", "音效策略"):
            self.assertIn(label, text)
        self.assertIn("主感觉：特效拉满", text)

    def test_the_rhythm_multiplier_reshapes_a_base_shot_length(self):
        fast = intent.decode("", primary="tight_fight")
        slow = intent.decode("", primary="tragic")

        self.assertLess(fast.shot_seconds(5), 5)
        self.assertGreater(slow.shot_seconds(5), 5)

    def test_every_intent_is_a_complete_usable_entry(self):
        for item in intent.INTENTS:
            with self.subTest(item.id):
                self.assertTrue(item.triggers and item.camera and item.composition)
                self.assertAlmostEqual(sum(item.sizes), 1.0, places=2)
                self.assertGreaterEqual(item.vfx_density, 0.0)
                self.assertLessEqual(item.vfx_density, 1.0)
                for other in item.conflicts:
                    self.assertIsNotNone(intent.get_intent(other), f"{item.id} 指向了不存在的冲突项 {other}")


class GenreRoutingTests(unittest.TestCase):
    def test_a_known_genre_key_routes_straight_to_its_cluster(self):
        self.assertEqual(clusters.cluster_for("xianxia").id, "C")
        self.assertEqual(clusters.cluster_for("mystery").id, "E")
        self.assertEqual(clusters.cluster_for("comedy").id, "G")

    def test_an_unknown_genre_is_read_from_the_story_itself(self):
        mystery = clusters.cluster_for("", text="深夜老宅，女主追查妹妹的失踪案，密室里只剩一只鞋")
        fight = clusters.cluster_for("", text="巷战开始，他一拳打翻追兵，枪声从街口传来")

        self.assertEqual(mystery.id, "E")
        self.assertEqual(fight.id, "D")

    def test_a_story_with_no_signal_falls_back_to_urban_drama(self):
        self.assertEqual(clusters.cluster_for("", text="他们在说话").id, clusters.DEFAULT_CLUSTER_ID)

    def test_the_cluster_decides_the_rhythm_label_and_whether_fights_are_normal(self):
        xianxia, drama = clusters.get_cluster("C"), clusters.get_cluster("A")

        self.assertEqual((xianxia.rhythm_profile, xianxia.fight_coverage), ("action", True))
        self.assertEqual((drama.rhythm_profile, drama.fight_coverage), ("confrontation", False))

    def test_a_direction_carries_both_the_cluster_and_the_decoded_feeling(self):
        plan = clusters.plan_direction(genre="mystery", text="老宅追查失踪案", brief="要压抑一点")

        self.assertEqual(plan.cluster.id, "E")
        self.assertEqual(plan.intent.primary.id, "oppressive")
        self.assertIn("【题材】悬疑惊悚（E簇）", plan.brief())
        self.assertIn("【感觉】", plan.brief())
        self.assertEqual(plan.as_dict()["rhythm_profile"], "suspense")

    def test_a_story_without_a_stated_feeling_takes_the_clusters_own(self):
        plan = clusters.plan_direction(genre="comedy", text="他把蛋糕扣在自己脸上")

        self.assertEqual(plan.intent.primary.id, "comedic")

    def test_a_task_uses_its_configured_feeling_over_the_words_of_its_brief(self):
        config = {"title_suggestion": "要唯美治愈一点", "primary_intent": "eerie", "secondary_intents": ["tension"]}

        plan = clusters.direction_from_task(config, genre="mystery", text="老宅")

        self.assertEqual(plan.intent.primary.id, "eerie")
        self.assertEqual([item.id for item in plan.intent.secondary], ["tension"])

    def test_every_cluster_points_at_real_negative_modules_and_a_real_intent(self):
        from app.core.agent_council import NEGATIVE_MODULE_WORDS

        for cluster in clusters.CLUSTERS:
            with self.subTest(cluster.id):
                self.assertIsNotNone(intent.get_intent(cluster.default_intent))
                for module in cluster.negative_modules:
                    self.assertIn(module, NEGATIVE_MODULE_WORDS, f"{cluster.id} 指向了不存在的负面词模块 {module}")


class StageFourWiringTests(unittest.TestCase):
    def test_the_table_writer_is_told_the_genre_and_the_feeling(self):
        from pathlib import Path

        import app.service.drama_service as service

        source = Path(service.__file__).read_text(encoding="utf-8")

        for marker in (
            "genre_clusters.direction_from_task(config, genre=genre, text=scene_content)",
            'user_prompt += "\\n" + direction.brief()',
            "direction.cluster.rhythm_profile",
            '"direction": direction.as_dict()',
        ):
            self.assertIn(marker, source, f"第4阶段题材/感觉接线点丢失：{marker}")


if __name__ == "__main__":
    unittest.main()
