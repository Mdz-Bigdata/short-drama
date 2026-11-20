"""剧本与分镜的手艺章节：主角拷问与人物关系、情绪钩子六步进编剧提示词，高张力镜头只给高张力场次。"""

import unittest

from app.core import prompt_data
from app.core.scene_tension import looks_tense, tension_hits
from app.core.screenwriting import prompts
from app.service import screenwriting_service as screenwriting


class WriterCraftTests(unittest.TestCase):
    def test_the_writer_is_asked_to_interrogate_the_lead_and_build_relationships(self):
        prompt = screenwriting.writer_system_prompt("你是编剧。", stage="write")
        self.assertIn("主角拷问与人物关系架法", prompt)
        self.assertIn("致命的软肋", prompt)
        self.assertIn("一部戏只有一条主线", prompt)

    def test_the_extraction_calls_do_not_pay_for_it(self):
        self.assertNotIn("致命的软肋", screenwriting.writer_system_prompt("你是编剧。", stage="extract"))


def _outline_prompt(**overrides):
    arguments = dict(
        title="周记", director_plan="策划", overview={"genre": "家庭伦理"}, first=1, last=1, total=3,
        context_entries=[], target_seconds=90, instructions=None,
    )
    return prompts.build_outline_plan_prompt(**{**arguments, **overrides})


def _script_prompt(**overrides):
    arguments = dict(
        source_text="大纲", source_kind="outline", episode=1, overview={}, style="", characters={}, scenes={}, props={},
        supported_durations=[5, 10], default_duration=None, episode_target_seconds=None,
        episode_outline={"story_beats": ["【悬念】小满站在收铺子的人里"], "hook": "【两难选择】笔尖悬在契上"},
        next_episode_outline={"title": "买主", "story_beats": ["【揭秘】买主一栏写的是周记"]},
    )
    return prompts.build_script_plan_prompt(**{**arguments, **overrides})


def _split_prompt(source_kind, max_episodes=3):
    return prompts.build_anchored_plan_prompt(
        window="他把笔递了过来。", window_is_final=True, overview={}, source_kind=source_kind, context_entries=[],
        target_volume=None, max_episodes=max_episodes, remaining_episodes=None, instructions=None,
    )


class EmotionalHookTests(unittest.TestCase):
    """情绪钩子六步：知识源给写的人讲透，三条规则各落在它管得着的那一步，只给有集尾卡点的连续剧。"""

    STEPS = ("共情基点", "反常裂痕", "抬高代价", "封死退路", "误导拉扯", "卡点")
    OUTLINE_RULE = prompt_data.text("emotional_hook", "outline_rule")
    LANDING_RULE = prompt_data.text("emotional_hook", "landing_rule")
    CUT_RULE = prompt_data.text("emotional_hook", "cut_rule")

    def test_the_writer_reads_the_six_steps_and_the_red_lines_whole(self):
        prompt = screenwriting.writer_system_prompt("你是编剧。", stage="write")
        self.assertIn("情绪钩子六步法", prompt)
        for step in (*self.STEPS, "反向爆击"):
            self.assertIn(step, prompt)
        for red_line in ("悬念和情绪脱节", "代价虚浮", "揭秘太快"):
            self.assertIn(red_line, prompt)
        # 排在最后的自检也读得到：默认预算装得下整篇，没有被截断。
        self.assertIn("下一集开场接的是不是这个空", prompt)

    def test_the_calls_that_do_not_write_hooks_do_not_pay_for_it(self):
        for stage in ("visual", "extract"):
            self.assertNotIn("反常裂痕", screenwriting.writer_system_prompt("你是编剧。", stage=stage))

    def test_the_outline_orders_the_beats_before_the_cliffhanger(self):
        # 规则开头就说「卡点先绑住人」，所以最后一步按它的括注「（卡点）」找。
        positions = [self.OUTLINE_RULE.index(step) for step in (*self.STEPS[:-1], "（卡点）")]
        self.assertEqual(positions, sorted(positions), "六步在规则里按顺序出现")
        self.assertIn("不写「天下大乱」这类宏大空话", self.OUTLINE_RULE)
        prompt = _outline_prompt()
        self.assertIn(self.OUTLINE_RULE, prompt)
        # 卡点类型表与信息位的规则还在：情绪钩子排在它们之后，三条同时生效。
        self.assertIn("钩子是把话留一半", prompt)
        self.assertLess(prompt.index("集尾卡点换着用"), prompt.index(self.OUTLINE_RULE))

    def test_films_that_close_their_own_story_are_not_asked_for_a_cliffhanger(self):
        # 广告落在行动号召上，电影短片只有一集、结尾收住，只有一集的剧没有下一集可卡。
        for mode in ("ad", "film"):
            self.assertNotIn(self.OUTLINE_RULE, _outline_prompt(creation_mode=mode))
            self.assertNotIn(self.LANDING_RULE, _script_prompt(creation_mode=mode))
        self.assertNotIn(self.OUTLINE_RULE, _outline_prompt(total=1))

    def test_an_authored_ending_stops_at_the_peak(self):
        for mode in ("drama", "narration"):
            prompt = _script_prompt(creation_mode=mode)
            self.assertIn("最后一格停在情绪最高的那一下", prompt)
            self.assertIn("读得出两种意思的动作或半句台词", prompt)
        self.assertNotIn(self.LANDING_RULE, _script_prompt(episode_outline={"story_beats": ["【冲突】a"]}), "没有钩子的集不附")

    def test_the_last_episode_is_left_to_close_the_story(self):
        self.assertNotIn(self.LANDING_RULE, _script_prompt(next_episode_outline=None))

    def test_an_adapted_ending_keeps_the_source(self):
        # 改编的集结尾在哪、说了什么都是原文的：不附落法。
        for kind in ("novel", "screenplay"):
            self.assertNotIn(self.LANDING_RULE, _script_prompt(source_kind=kind, source_text="他把笔递了过来。"))

    def test_a_novel_is_cut_at_the_peak_and_a_screenplay_keeps_its_own_episodes(self):
        self.assertIn(self.CUT_RULE, _split_prompt("novel"))
        self.assertIn("用一句对白或一件看得见的东西带回来，不另编", self.CUT_RULE)
        self.assertNotIn(self.CUT_RULE, _split_prompt("screenplay"))
        self.assertNotIn(self.CUT_RULE, _split_prompt("novel", max_episodes=1), "只切成一集就没有卡点")

    def test_the_landing_rule_stays_out_of_the_fight_detection_text(self):
        # 打戏规则按本集大纲的字面判断要不要装；落法里的词不能把文戏集判成打戏集。
        self.assertNotIn(self.LANDING_RULE, prompts._outline_block({"hook": "笔尖悬在契上"}, {"title": "买主"}))


class SceneTensionTests(unittest.TestCase):
    def test_a_standoff_reads_as_tense(self):
        scene = "陆行远步步紧逼，把她逼到墙角，冷笑着质问账本的下落；两人对视，屋里一片死寂。"
        self.assertTrue(looks_tense(scene))
        self.assertGreaterEqual(len(tension_hits(scene)), 2)

    def test_tension_written_into_hands_and_blades_reads_as_tense(self):
        # 剧本不写心理：她的张力在手上和刀上。
        self.assertTrue(looks_tense("裘三娘没有向前一步，只把左手移到腰间刀柄上，五指一根根收紧，指节顶出白痕。"))

    def test_an_everyday_scene_does_not(self):
        self.assertFalse(looks_tense("清晨的早点铺，她给弟弟盛了一碗豆浆，两人说说笑笑地出门上学。"))
        self.assertFalse(looks_tense("他沉默地吃完了面。"), "one word alone is not enough")


class StoryboardRuleTests(unittest.TestCase):
    def test_scale_is_written_with_a_reference_and_actions_as_a_chain(self):
        rules = prompt_data.text("storyboard_hard_rules", "text")
        self.assertIn("写画面里的参照物", rules)
        self.assertIn("抬手→停住半拍→转身", rules)


if __name__ == "__main__":
    unittest.main()
