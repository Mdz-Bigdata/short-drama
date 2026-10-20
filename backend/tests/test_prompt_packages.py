# -*- coding: utf-8 -*-
"""Seedance prompt packages: a shot table re-cut into what a model can hold.

A storyboard shot is a unit of story; a generation shot is about four seconds of one
continuous action. Each package must stand on its own — its own locks, its own clock —
because the model never saw the package before it.
"""

import unittest

from app.core import prompt_packages as packages
from app.core import style_packs

SHOTS = [
    {
        "shot_id": 1, "size": "全景", "motion": "固定", "duration": "6s",
        "desc": "林夏推门进来，停在桌前。她把录音笔放在桌沿，指尖压住。",
        "characters": ["林夏", "周教授"], "dialogue": "林夏：你到底瞒了什么？", "sound": "环境音：空调低鸣",
    },
    {
        "shot_id": 2, "size": "近景", "motion": "缓推", "duration": "5s",
        "desc": "周教授摘下眼镜，慢慢擦拭，抬眼时目光变冷。",
        "characters": ["周教授"], "dialogue": "周教授：够了。", "sound": "动作音：镜片摩擦",
    },
    {
        "shot_id": 3, "size": "特写", "motion": "固定", "duration": "4s",
        "desc": "录音笔红灯闪烁，桌面映出两人的影子。", "characters": [], "dialogue": "",
    },
]


def _context(**overrides) -> packages.PackageContext:
    values = dict(
        pack=style_packs.FILM_35MM, scene="办公室 夜 内景",
        spatial_lock="林夏恒在画左、周教授恒在画右，书案居中",
        lighting="冷白顶光 5000K，光比3:1",
        cast_locks={"林夏": "青灰大衣、齐耳短发", "周教授": "花白头发、深色西装"},
    )
    values.update(overrides)
    return packages.PackageContext(**values)


class RecutTests(unittest.TestCase):
    def test_a_shot_is_split_at_its_own_beats_and_never_past_the_ceiling(self):
        pieces = packages.recut(SHOTS[0])

        self.assertEqual([piece.beat for piece in pieces], [1, 2])
        self.assertTrue(all(piece.seconds <= packages.MAX_GENERATED_SECONDS for piece in pieces))
        self.assertAlmostEqual(sum(piece.seconds for piece in pieces), 6.0, delta=0.5)
        self.assertEqual(pieces[0].action, "林夏推门进来，停在桌前")

    def test_the_slices_are_uneven_because_the_beats_are(self):
        pieces = packages.recut({
            "shot_id": 9, "duration": "8s", "size": "中景", "motion": "固定",
            "desc": "他抬眼。他缓缓站起身，绕过长桌走到窗边，推开那扇积了灰的窗户。",
        })

        lengths = {piece.seconds for piece in pieces}
        self.assertGreater(len(lengths), 1, "每段都一样长就不是按节拍切的")

    def test_a_line_lives_in_one_generated_shot(self):
        pieces = packages.recut(SHOTS[1])

        spoken = [piece for piece in pieces if piece.dialogue]
        self.assertEqual(len(spoken), 1)
        self.assertEqual(spoken[0].dialogue, "周教授：够了。")

    def test_a_long_shot_is_cut_into_enough_pieces_to_fit(self):
        pieces = packages.recut({
            "shot_id": 4, "duration": "12s", "size": "中景", "motion": "固定",
            "desc": "她站起身。她走向门口。她停下。她回头看了一眼。",
        })

        self.assertGreaterEqual(len(pieces), 3)
        self.assertTrue(all(piece.seconds <= packages.MAX_GENERATED_SECONDS for piece in pieces))


class PackagingTests(unittest.TestCase):
    def test_packages_fill_to_the_requested_length_and_restart_their_clock(self):
        plan = packages.plan_packages(SHOTS, package_seconds=10)

        self.assertGreaterEqual(len(plan.packages), 2)
        for package in plan.packages:
            self.assertLessEqual(package.seconds, 10)
            self.assertEqual(package.shots[0].start_seconds, 0.0)
            self.assertEqual([shot.index for shot in package.shots], list(range(1, len(package.shots) + 1)))
        # The episode clock still runs across packages even though each one starts at zero.
        self.assertEqual(plan.packages[0].episode_start, 0.0)
        self.assertEqual(plan.packages[1].episode_start, plan.packages[0].episode_end)

    def test_the_package_count_follows_the_episode_length(self):
        self.assertEqual(packages.package_count(90, 15), 6)
        self.assertEqual(packages.package_count(90, 30), 3)
        self.assertEqual(packages.package_count(95, 30), 4)      # the last one may be short
        self.assertEqual(packages.package_count(0, 15), 1)

    def test_a_fight_cuts_shorter_than_a_drama(self):
        drama = packages.plan_packages(SHOTS, package_seconds=15)
        fight = packages.plan_packages(SHOTS, package_seconds=15, variant="fight")

        self.assertLessEqual(max(shot.seconds for package in fight.packages for shot in package.shots), 3.0)
        self.assertGreater(
            sum(len(package.shots) for package in fight.packages),
            sum(len(package.shots) for package in drama.packages),
        )

    def test_a_line_that_cannot_be_said_in_its_shot_is_reported(self):
        long_line = dict(SHOTS[1], dialogue="周教授：这件事从一开始就不是你想的那样，我替你压了整整三年。")

        plan = packages.plan_packages([long_line], package_seconds=10, delivery="沉重")

        self.assertTrue(any("语速" in warning for warning in plan.warnings))

    def test_the_settings_are_checked(self):
        with self.assertRaises(ValueError):
            packages.plan_packages(SHOTS, package_seconds=12)
        with self.assertRaises(ValueError):
            packages.plan_packages(SHOTS, delivery="随便")
        self.assertEqual(packages.plan_packages([], package_seconds=15).packages, [])


class RenderingTests(unittest.TestCase):
    def test_a_package_carries_its_own_locks_negatives_and_divider(self):
        plan = packages.plan_packages(SHOTS, package_seconds=10)

        text = packages.render(plan, _context(), title="暗室回声")

        self.assertIn("【提示词1】【00:00 - ", text)
        self.assertIn("<Asset_Setup>", text)
        self.assertIn("全局风格锁：", text)
        self.assertIn("出场资产锁：林夏：青灰大衣、齐耳短发", text)
        self.assertIn("光影基调锁：冷白顶光 5000K", text)
        self.assertIn("物理状态遗留：", text)
        self.assertIn("【空间坐标与专属背景锁】：林夏恒在画左", text)
        self.assertIn("【负面词约束】", text)
        self.assertEqual(text.count(packages.DIVIDER), len(plan.packages))
        # Every package repeats the locks: it is pasted on its own.
        self.assertEqual(text.count("<Asset_Setup>"), len(plan.packages))

    def test_each_package_states_what_it_is_most_likely_to_drift_on(self):
        text = packages.render(packages.plan_packages(SHOTS, package_seconds=10), _context())

        self.assertIn("禁止两人面部特征互换", text)
        self.assertIn("禁止口型与台词不同步", text)

    def test_the_continuous_variant_forbids_cutting(self):
        plan = packages.plan_packages(SHOTS, package_seconds=15, variant="continuous")

        text = packages.render(plan, _context())

        self.assertIn("【全局锁定】", text)
        self.assertIn("【连续性总约束】", text)
        self.assertIn("禁止切镜", text)

    def test_the_fight_variant_states_the_rules_once_then_short_beats(self):
        plan = packages.plan_packages(SHOTS, package_seconds=10, variant="fight")

        text = packages.render(plan, _context())

        self.assertIn("【整体战斗设定】", text)
        self.assertIn("【分镜】", text)
        self.assertIn("禁止站桩轮流出招", text)
        self.assertIn("禁止定格、停格、子弹时间", text)

    def test_the_script_document_lists_assets_then_every_line_then_the_shots(self):
        plan = packages.plan_packages(SHOTS, package_seconds=15, variant="script_doc")

        text = packages.render(plan, _context(), title="暗室回声")

        self.assertLess(text.index("## 角色与场景资产清单"), text.index("## 完整台词本"))
        self.assertLess(text.index("## 完整台词本"), text.index("## 分镜脚本"))
        self.assertIn("@林夏：青灰大衣、齐耳短发", text)
        self.assertIn("台词01", text)
        self.assertIn("Shot 1.1", text)
        self.assertIn("【分段时长核验】", text)
        self.assertIn("→ 动作桥接：", text)

    def test_a_script_segment_stays_inside_its_caps(self):
        many = [dict(SHOTS[0], shot_id=index, duration="6s") for index in range(1, 9)]
        plan = packages.plan_packages(many, package_seconds=15, variant="script_doc")

        text = packages.render(plan, _context())

        for line in text.splitlines():
            if line.startswith("【分段时长核验】"):
                shots_in = int(line.split("】")[1].split(" 镜")[0])
                seconds = float(line.split("/ ")[1].split(" 秒")[0])
                self.assertLessEqual(shots_in, packages.MAX_SEGMENT_SHOTS)
                self.assertLessEqual(seconds, packages.MAX_SEGMENT_SECONDS)


if __name__ == "__main__":
    unittest.main()


class ExportApiTests(unittest.TestCase):
    """Both exports are read-only views of an approved shot table."""

    def setUp(self):
        import tempfile
        from pathlib import Path

        from app.api import drama_api
        from app.api.auth_api import get_current_user
        from app.repository.task_repo import TaskRepository
        from main import app

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        drama_api.service.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "export-user", "role": "user"}
        self.addCleanup(app.dependency_overrides.clear)

        from fastapi.testclient import TestClient

        self.client = TestClient(app)
        self.service = drama_api.service
        self.task_id = "export-task"
        self.service.repo.save_task(self.task_id, {
            "task_id": self.task_id, "owner_user_id": "export-user", "current_stage": 4, "status": "idle",
            "config": {"title_suggestion": "暗室回声", "style_pack": "film_35mm", "video_model": "seedance2.5"},
            "assets": {
                "4": [dict(shot, scene_id="E1S01", scene="办公室 夜 内景") for shot in SHOTS],
                "3_characters": [{"name": "林夏", "desc": "青灰大衣"}, {"name": "周教授", "desc": "花白头发"}],
                "2_breakdown": {
                    "scenes": [{"scene_id": "E1S01", "content": "林夏与周教授在办公室对峙"}],
                    "production_assets": {
                        "scenes": [{"name": "办公室", "description": "北侧档案柜，冷白顶灯，深夜"}],
                        "props": [{"name": "录音笔", "description": "银色外壳"}],
                    },
                },
            },
            "logs": {}, "episodes": [],
        })

    def test_the_packages_endpoint_returns_pasteable_text_and_its_plan(self):
        response = self.client.get(
            f"/api/drama/{self.task_id}/prompt-packages",
            params={"scene_id": "E1S01", "package_seconds": 10, "delivery": "正常"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["plan"]["package_seconds"], 10)
        self.assertGreaterEqual(len(payload["plan"]["packages"]), 2)
        self.assertIn("【提示词1】", payload["text"])
        self.assertIn("出场资产锁：林夏：青灰大衣", payload["text"])
        self.assertIn("35mm", payload["text"])          # the project's style pack reached the export

    def test_the_variant_and_the_length_are_validated(self):
        self.assertEqual(
            self.client.get(f"/api/drama/{self.task_id}/prompt-packages", params={"package_seconds": 12}).status_code,
            422,
        )
        self.assertEqual(
            self.client.get(f"/api/drama/{self.task_id}/prompt-packages", params={"variant": "nope"}).status_code,
            422,
        )
        self.assertEqual(
            self.client.get(f"/api/drama/{self.task_id}/prompt-packages", params={"variant": "script_doc"}).status_code,
            200,
        )

    def test_a_project_without_a_shot_table_is_told_what_is_missing(self):
        self.service.repo.save_task("empty-task", {
            "task_id": "empty-task", "owner_user_id": "export-user", "current_stage": 2, "status": "idle",
            "config": {"title_suggestion": "空项目"}, "assets": {}, "logs": {}, "episodes": [],
        })

        response = self.client.get("/api/drama/empty-task/prompt-packages")

        self.assertEqual(response.status_code, 422)
        self.assertIn("第4阶段", response.json()["detail"])

    def test_the_asset_sheets_endpoint_returns_the_four_blocks(self):
        response = self.client.get(f"/api/drama/{self.task_id}/asset-sheets")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual([sheet["name"] for sheet in payload["sheets"]["characters"]], ["林夏", "周教授"])
        self.assertEqual(payload["sheets"]["scenes"][0]["name"], "顶灯深夜办公室")
        self.assertIn("【人物资产】", payload["markdown"])
        self.assertIn("不能出现其他人", payload["markdown"])

    def test_a_missing_task_is_a_404(self):
        self.assertEqual(self.client.get("/api/drama/no-such-task/asset-sheets").status_code, 404)
