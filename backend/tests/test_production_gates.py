import inspect
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from app.core import agent_council, media_compositor, storyboard_revision
from app.core.screenwriting import prompts
from app.core.shot_table_rules import audit_shot_table


def _shot(desc, *cast):
    return {"desc": desc, "characters": list(cast)}


class ManyPeopleAndActionsTests(unittest.TestCase):
    def test_a_crowded_busy_shot_is_not_sent_back(self):
        shots = [
            {**_shot("甲一转身，然后拔剑，接着冲向门口，随后回头", "甲一", "乙二", "丙三", "丁四", "戊五"), "motion": "固定"},
            {**_shot("五人围住供桌，然后同时落座，接着举杯", "甲一", "乙二", "丙三", "丁四", "戊五"), "motion": "固定"},
        ]
        self.assertEqual([issue for issue in storyboard_revision.handoff_issues(shots, scene_id="E1S01") if "动作" in issue or "露面" in issue], [])

    def test_the_table_audit_does_not_count_heads(self):
        shots = [{"shot_id": 1, "desc": "甲乙丙丁戊五人同时起身，" + "围着供桌" * 20, "size": "全景", "characters": ["甲一", "乙二", "丙三", "丁四", "戊五"], "duration": "6s"}]
        rules = [issue.rule for issue in audit_shot_table(shots, video_model="seedance2.0", whole_episode=False).issues]
        self.assertNotIn("同框清晰人物过多", rules)

    def test_the_writer_is_told_it_may(self):
        self.assertNotIn("不超过 3 人", inspect.getsource(prompts))
        self.assertNotIn("每镜只推进", inspect.getsource(agent_council))


class PropContinuityTests(unittest.TestCase):
    def test_a_prop_in_hand_from_nowhere_is_caught(self):
        shots = [_shot("沈砚走进宗祠", "沈砚"), _shot("沈砚攥紧长剑，盯着门口", "沈砚")]
        issues = storyboard_revision.prop_issues(shots, ["长剑"])
        self.assertEqual(len(issues), 1)
        self.assertIn("第2镜「长剑」已经在手上", issues[0])

    def test_picking_it_up_or_showing_it_first_is_fine(self):
        picked = [_shot("沈砚走进宗祠", "沈砚"), _shot("沈砚拔出长剑", "沈砚")]
        shown = [_shot("长剑挂在墙上", "沈砚"), _shot("沈砚握着长剑", "沈砚")]
        opening = [_shot("沈砚握着长剑站在门口", "沈砚")]
        for shots in (picked, shown, opening):
            self.assertEqual(storyboard_revision.prop_issues(shots, ["长剑"]), [])

    def test_a_prop_merely_seen_is_not_in_hand(self):
        shots = [_shot("沈砚走进宗祠", "沈砚"), _shot("镜头落在供桌的玉牌上", "沈砚")]
        self.assertEqual(storyboard_revision.prop_issues(shots, ["玉牌"]), [])

    def test_the_hand_cannot_change_without_being_written(self):
        swapped = [_shot("沈砚右手握着长剑", "沈砚"), _shot("沈砚左手握着长剑", "沈砚")]
        self.assertIn("从右手到了左手", storyboard_revision.prop_issues(swapped, ["长剑"])[0])
        written = [_shot("沈砚右手握着长剑", "沈砚"), _shot("沈砚换手，左手握着长剑", "沈砚")]
        self.assertEqual(storyboard_revision.prop_issues(written, ["长剑"]), [])

    def test_two_people_may_hold_it_in_different_hands(self):
        shots = [_shot("沈砚右手握着长剑", "沈砚", "林晚"), _shot("林晚左手接过长剑", "沈砚", "林晚")]
        self.assertEqual(storyboard_revision.prop_issues(shots, ["长剑"]), [])

    def test_the_checks_reach_the_revision(self):
        shots = [{**_shot("沈砚走进宗祠", "沈砚"), "motion": "固定"}, {**_shot("沈砚攥紧长剑", "沈砚"), "motion": "固定"}]
        self.assertTrue(any("长剑" in issue for issue in storyboard_revision.handoff_issues(shots, scene_id="E1S01", props=["长剑"])))


class PayoffFormulaTests(unittest.TestCase):
    def test_only_payoff_genres_get_it(self):
        block = prompts._payoff_block({"genre": "赘婿复仇古装"})
        for rule in ("杀伐果断", "横推无敌", "弱时苟、强时杀", "不按套路"):
            self.assertIn(rule, block)
        self.assertIn("杀伐果断", prompts._payoff_block({"genre": "凡人修仙"}))
        self.assertEqual(prompts._payoff_block({"genre": "家庭伦理"}), "")
        self.assertEqual(prompts._payoff_block(None), "")

    def test_the_outline_prompt_carries_it(self):
        made = prompts.build_outline_plan_prompt(
            **_outline_arguments(prompts.build_outline_plan_prompt, {"genre": "都市逆袭"}),
        )
        self.assertIn("主角三不", made)
        calm = prompts.build_outline_plan_prompt(**_outline_arguments(prompts.build_outline_plan_prompt, {"genre": "家庭伦理"}))
        self.assertNotIn("主角三不", calm)


def _outline_arguments(builder, overview):
    import inspect

    samples = {"title": "剧", "overview": overview, "first": 1, "last": 1, "total": 3}
    arguments = {}
    for name, parameter in inspect.signature(builder).parameters.items():
        if parameter.default is inspect.Parameter.empty:
            arguments[name] = samples.get(name, "")
    return arguments


class NoAiMarkTests(unittest.TestCase):
    # Real ffmpeg: nothing in the picture, nothing in the file.

    def test_the_film_has_no_mark_in_its_picture_or_its_file(self):
        ffmpeg = media_compositor._ffmpeg()
        ffprobe = shutil.which("ffprobe") or str(ffmpeg).replace("ffmpeg", "ffprobe")
        if not ffmpeg or not os.path.exists(ffprobe):
            self.skipTest("ffmpeg unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clip = root / "clip.mp4"
            subprocess.run(
                [ffmpeg, "-y", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=0x2040A0:s=160x284:d=3:r=30",
                 "-vf", "noise=alls=8:allf=t", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)], check=True,
            )

            def fetch(_url, target):
                shutil.copyfile(clip, target)
                return True

            with patch.object(media_compositor, "MEDIA_DIR", str(root)), patch.object(media_compositor, "_download", side_effect=fetch):
                url = media_compositor.compose_film(["http://clips.test/a.mp4"], [""], None, tag="plain", title=None, bgm=False)
            film = root / url.rsplit("/", 1)[-1]
            frame = root / "frame.png"
            subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-ss", "1", "-i", str(film), "-frames:v", "1", str(frame)], check=True)
            with Image.open(frame) as picture:
                self.assertLess(max(picture.convert("L").crop((48, 150, 200, 206)).getdata()), 200)
            tags = subprocess.run([ffprobe, "-v", "error", "-show_entries", "format_tags", "-of", "json", str(film)],
                                  check=True, capture_output=True, text=True).stdout
            self.assertNotIn("AIGC", tags)
            self.assertNotIn("ProduceID", tags)

    def test_the_title_card_says_nothing_about_ai(self):
        environment = {key: value for key, value in os.environ.items() if key != "TITLE_CARD_TAGLINE"}
        with patch.dict(os.environ, environment, clear=True):
            self.assertEqual(media_compositor._title_tagline(), "")
        self.assertNotIn("AI", media_compositor.UNTITLED_FILM)


if __name__ == "__main__":
    unittest.main()
