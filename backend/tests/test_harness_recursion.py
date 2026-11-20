"""The stage agents' self-improvement: propose, probe, compose, blind selection, reflection, library.

No model and no network: the improving model and the stage call are scripted, and the library is
written to a temporary folder.
"""

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import harness_recursion
from app.core.harness_recursion import harness as surface
from app.core.harness_recursion import checks, library, prompts, selection
from app.core.harness_recursion.recursion import BudgetError, Ledger, run_stage

OUTPUT = "方案正文。" * 60
INV_EDIT = "<notes>新增 -> system_prompt -> 原产出漏了分集钩子</notes><harness><system_prompt>先列分集钩子再写正文</system_prompt></harness>"
DOM_EDIT = "<notes>新增 -> skills -> 人物关系没交代</notes><harness><skills>当出现两个以上主要人物时：先写清他们的关系</skills></harness>"
MERGED = (
    "<notes>保留 -> inv1 的顺序 -> inv1 的产出先有钩子\n保留 -> dom1 的关系 -> dom1 的产出交代了关系</notes>"
    "<harness><system_prompt>先列分集钩子再写正文</system_prompt><skills>当出现两个以上主要人物时：先写清他们的关系</skills></harness>"
)
KEEP = "<notes>记录不支持任何改动</notes><harness>KEEP_BASE</harness>"
EXPERIENCE = (
    "<edits>\ncomponent: system_prompt\ncandidates: inv1, agg1\nchange: 先列钩子\nobserved: agg1 的产出每集开头有钩子\nverdict: helped\n</edits>\n"
    "<experience>\ncue: 方案要交给编剧分集时\nlesson: 在 system_prompt 里要求先列每集钩子再写正文\n"
    "evidence: system_prompt 那一条；agg1 与 base1 的产出对比\nconfidence: {confidence}，两次执行都体现\n</experience>"
)


class Script:
    """A scripted improving model and stage call that remember what they were shown."""

    def __init__(self, *, inv=INV_EDIT, dom=DOM_EDIT, compose=MERGED, choose="final", reflect=EXPERIENCE.format(confidence="high")):
        self.replies = {"INV": inv, "DOM": dom, "COMPOSE": compose}
        self.choose, self.reflection = choose, reflect
        self.missions: list[tuple[str, str, str]] = []
        self.executed: list[str] = []
        self.lock = threading.Lock()

    def kind(self, mission: str) -> str:
        if "```choice" in mission:
            return "SELECT"
        if "<experience>" in mission:
            return "REFLECT"
        if prompts.says("compose", "head") in mission:
            return "COMPOSE"
        return "INV" if prompts.says("propose", "inv") in mission else "DOM"

    def improver(self, mission: str, material: str) -> str:
        kind = self.kind(mission)
        with self.lock:
            self.missions.append((kind, mission, material))
            seen = sum(1 for item in self.missions if item[0] == kind)
        if kind == "SELECT":
            ids = [line.split()[2] for line in material.splitlines() if line.startswith("## 候选 ")]
            wanted = "改过的产出" if self.choose == "final" else OUTPUT[:20]
            blocks = material.split("## 候选 ")[1:]
            picked = next((block.split()[0] for block in blocks if (wanted in block) == (self.choose == "final") or self.choose == "base" and "改过的产出" not in block), ids[0])
            if self.choose == "garbled":
                return "我选不出来"
            return f"<why>交付完整，下游能直接用</why>\n```choice\n{picked}\n```"
        if kind == "REFLECT":
            return self.reflection
        reply = self.replies[kind]
        return reply[min(seen, len(reply)) - 1] if isinstance(reply, list) else reply

    def execute(self, overlay: str) -> str:
        with self.lock:
            self.executed.append(overlay)
        return ("改过的产出：" + overlay + "。") + OUTPUT if overlay else OUTPUT


class RecursionTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        patcher = patch.object(library, "LIBRARY_ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def work(self, script: Script, **overrides) -> harness_recursion.Work:
        values = dict(
            task_id="task-0001", stage=1, domain="古装武侠", work="总导演写定调方案", downstream="编剧",
            request="请为短剧《刀不认人》做导演方案定调", execute=script.execute, improver=script.improver,
        )
        return harness_recursion.Work(**{**values, **overrides})

    def test_one_parallel_step_spends_four_executions_and_three_improvements_and_keeps_its_lesson(self):
        script = Script()
        record = harness_recursion.step(self.work(script), base_outputs=[OUTPUT])
        ledger = record.result.ledger
        self.assertEqual((len(ledger.rollouts), len(ledger.sessions)), (4, 3))
        self.assertEqual(ledger.rollouts, ["base1", "inv1", "dom1", "agg1"])
        self.assertEqual(record.result.finals, ["agg1"])
        # The stage's own output is the base execution: only the three edited overlays are run.
        self.assertEqual(len(script.executed), 3)
        self.assertTrue(all(prompts.says("overlay", "header") in overlay for overlay in script.executed))
        self.assertEqual(record.adopted, "agg1")
        self.assertEqual(set(record.adopted_harness), {"system_prompt", "skills"})
        self.assertTrue(record.applied)
        block = library.overlay_block(1, "古装武侠")
        self.assertIn("先列分集钩子再写正文", block)
        self.assertIn("当出现两个以上主要人物时", block)
        self.assertNotIn("先列每集钩子", block, "the lesson is written for whoever edits an overlay, not for the agent")
        self.assertEqual(library.overlay_block(1, "都市情感"), "", "another kind of production does not get this kind's overlay")
        self.assertEqual(library.overlay_block(8, "古装武侠"), "", "nor does another stage")

    def test_wider_and_deeper_budgets_land_on_the_same_identity(self):
        for mode, finals in (("agg", ["agg1", "agg2"]), ("seq", ["c1", "c2"])):
            script = Script()
            record = harness_recursion.step(self.work(script, task_id=f"task-{mode}"), base_outputs=[OUTPUT], k=2, mode=mode, remember=False)
            ledger = record.result.ledger
            self.assertEqual((len(ledger.rollouts), len(ledger.sessions)), (8, 6), mode)
            self.assertEqual(record.result.finals, finals)
            # k base executions: the stage's own output and one more run of the unchanged call.
            self.assertEqual(script.executed.count(""), 1, mode)

    def test_the_second_round_proposes_on_what_the_first_round_composed(self):
        script = Script()
        harness_recursion.step(self.work(script), base_outputs=[OUTPUT], k=2, mode="seq", remember=False)
        second_round = [material for kind, mission, material in script.missions if kind == "INV"][1]
        current = second_round.split(prompts.says("context", "current"))[1].split("# ")[0]
        self.assertIn("先列分集钩子再写正文", current)
        self.assertIn(f"上限合计 {prompts.limit('total_chars')} 字", current, "the author is told how much room is left")

    def test_a_ledger_off_its_budget_or_with_a_repeated_label_is_refused(self):
        with self.assertRaises(BudgetError):
            Ledger("agg", 1, rollouts=["base1", "inv1", "dom1"], sessions=["inv1", "dom1", "agg1"]).assert_identity()
        with self.assertRaises(BudgetError):
            Ledger("agg", 1, rollouts=["base1", "inv1", "inv1", "agg1"], sessions=["inv1x", "dom1x", "agg1x"]).assert_identity()

    def test_a_proposal_off_the_surface_is_sent_back_once_then_the_stage_keeps_what_it_had(self):
        stray = "<harness><plugins>拦截每次调用</plugins></harness>"
        asked: list[str] = []

        def improver(mission: str, material: str) -> str:
            asked.append(mission)
            return stray if len(asked) == 1 else INV_EDIT

        stage = run_stage(label="inv1", dim="INV", mission="M", material="E", fallback={}, improver=improver)
        self.assertFalse(stage.fell_back)
        self.assertEqual(stage.attempts, 2)
        self.assertIn("plugins", asked[1])
        self.assertIn("先列分集钩子", stage.harness["system_prompt"])

        stage = run_stage(label="inv1", dim="INV", mission="M", material="E", fallback={"memory": "本项目里主角姓沈"}, improver=lambda *_: stray)
        self.assertTrue(stage.fell_back)
        self.assertEqual(stage.harness, {"memory": "本项目里主角姓沈"})

    def test_an_overlay_about_being_judged_or_over_its_size_is_refused(self):
        with self.assertRaises(surface.ProposalError):
            surface.validate({"guardrails": "按评分标准写，争取质检分更高"})
        with self.assertRaises(surface.ProposalError):
            surface.validate({"memory": "字" * (prompts.limit("component_chars") + 1)})
        surface.validate({"guardrails": "不写没有出处的数据"})

    def test_a_reply_edits_the_current_overlay_in_place(self):
        current = {"memory": "本项目里主角姓沈", "skills": "当有打戏时：写清谁先出手"}
        merged = surface.parse_reply("<harness><skills></skills><guardrails>不写旁白</guardrails></harness>", current)
        self.assertEqual(merged, {"guardrails": "不写旁白", "memory": "本项目里主角姓沈"})
        self.assertEqual(surface.parse_reply(KEEP, current), surface.normalise(current))
        # The "(empty)" mark shown for an empty component, copied back, is still empty (seen in a real run).
        echoed = surface.parse_reply(f"<harness><scripts>{prompts.label('empty')}</scripts><memory>{prompts.label('empty')}</memory></harness>", current)
        self.assertEqual(echoed, {"skills": "当有打戏时：写清谁先出手"})
        self.assertEqual(surface.render({}), "", "an empty overlay adds nothing to the stage prompt")

    def test_when_nobody_changes_anything_nothing_is_run_again_and_nothing_is_learned(self):
        script = Script(inv=KEEP, dom=KEEP, compose=KEEP)
        record = harness_recursion.step(self.work(script), base_outputs=[OUTPUT])
        self.assertEqual(script.executed, [], "an unchanged overlay is not paid for a second time")
        self.assertEqual(record.adopted, "base1")
        self.assertFalse(record.applied)
        self.assertEqual(record.experience, {})
        self.assertEqual(library.entries(1, "古装武侠"), [])
        self.assertFalse(any(kind in ("SELECT", "REFLECT") for kind, _mission, _material in script.missions))

    def test_selection_sees_outputs_only_and_may_choose_the_unchanged_one(self):
        script = Script(choose="base")
        record = harness_recursion.step(self.work(script), base_outputs=[OUTPUT])
        shown = next(material for kind, _mission, material in script.missions if kind == "SELECT")
        for origin in ("agg1", "base1", "inv1", "<system_prompt>", prompts.says("context", "current")):
            self.assertNotIn(origin, shown)
        self.assertEqual(record.adopted, "base1")
        # The lesson is kept for later proposers to read, but no overlay reaches the stage prompts.
        self.assertFalse(record.applied)
        self.assertEqual(len(library.entries(1, "古装武侠")), 1)
        self.assertEqual(library.overlay_block(1, "古装武侠"), "")
        self.assertIn("先列每集钩子", library.context_block(1, "古装武侠"))

    def test_a_choice_that_cannot_be_read_keeps_the_unchanged_output(self):
        record = harness_recursion.step(self.work(Script(choose="garbled")), base_outputs=[OUTPUT])
        self.assertEqual(record.adopted, "base1")
        self.assertFalse(record.selection.ok)
        self.assertFalse(record.applied)

    def test_anonymous_ids_are_stable_for_a_task_and_hide_the_order(self):
        first = selection.assign_ids(["base1", "agg1", "agg2"], task_id="t", k=2, mode="agg")
        self.assertEqual(first, selection.assign_ids(["agg2", "base1", "agg1"], task_id="t", k=2, mode="agg"))
        self.assertEqual(sorted(first), ["A", "B", "C"])

    def test_a_reflection_that_declines_keeps_the_overlay_out_and_one_that_is_unsure_does_not(self):
        declined = harness_recursion.step(self.work(Script(reflect="<edits>component: skills\nverdict: confounded</edits>\nNO_ENTRY")), base_outputs=[OUTPUT])
        self.assertEqual(library.entries(1, "古装武侠"), [])
        self.assertFalse(declined.applied)

        # Unsure which single edit did the work is not a veto: the overlay as a whole won its comparison.
        unsure = harness_recursion.step(self.work(Script(reflect=EXPERIENCE.format(confidence="low")), task_id="task-0002"), base_outputs=[OUTPUT])
        self.assertTrue(unsure.applied)
        self.assertEqual(library.entries(1, "古装武侠")[0]["experience"]["confidence"][:3], "low", "what it said stays on record")
        self.assertIn("先列分集钩子再写正文", library.overlay_block(1, "古装武侠"))

        judged = selection.parse_experience(EXPERIENCE.format(confidence="high").replace("先列每集钩子", "按评分标准先列钩子"))
        self.assertFalse(selection.has_experience(judged), "a lesson about being judged is not kept")

    def test_a_stage_call_that_dies_is_evidence_and_not_an_error(self):
        script = Script()

        def execute(overlay: str) -> str:
            if "当出现两个以上" in overlay and "先列分集钩子" not in overlay:
                raise TimeoutError("provider timed out")
            return script.execute(overlay)

        record = harness_recursion.step(self.work(script, execute=execute), base_outputs=[OUTPUT], remember=False)
        self.assertFalse(record.result.rollouts["dom1"].ok)
        composer_saw = next(material for kind, _mission, material in script.missions if kind == "COMPOSE")
        self.assertIn("TimeoutError", composer_saw)
        self.assertEqual(record.adopted, "agg1")

    def test_later_proposers_read_the_library_and_a_retired_lesson_leaves_the_prompts(self):
        harness_recursion.step(self.work(Script()), base_outputs=[OUTPUT])
        script = Script()
        harness_recursion.step(self.work(script, task_id="task-0002"), base_outputs=[OUTPUT])
        proposer_saw = next(material for kind, _mission, material in script.missions if kind == "INV")
        self.assertIn("task-0001", proposer_saw)
        self.assertIn("先列每集钩子", proposer_saw)
        # The newest overlay that won replaces the one before it: nothing piles up.
        self.assertEqual(library.overlay_block(1, "古装武侠").count("先列分集钩子再写正文"), 1)
        self.assertTrue(library.retire(1, "古装武侠", "task-0002"))
        self.assertIn("先列分集钩子再写正文", library.overlay_block(1, "古装武侠"), "the one before it is current again")
        self.assertTrue(library.retire(1, "古装武侠", "task-0001"))
        self.assertEqual(library.overlay_block(1, "古装武侠"), "")
        self.assertEqual(library.report()["kinds"][0]["entries"], 2)

    def test_a_damaged_or_missing_library_reads_as_empty(self):
        self.assertEqual(library.entries(3, "没有这一类"), [])
        folder = library.domain_dir(1, "古装/武侠 ../x")
        self.assertEqual(folder.parent.parent, self.root, "a kind's name is one folder, never a path")
        folder.mkdir(parents=True)
        (folder / "broken.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(library.entries(1, "古装/武侠 ../x"), [])
        self.assertEqual(library.overlay_block(1, "古装/武侠 ../x"), "")

    def test_a_project_s_own_facts_stay_behind_and_the_next_study_edits_the_overlay_in_place(self):
        with_facts = MERGED.replace("</harness>", "<memory>本项目里主角姓沈，反派是他师兄</memory></harness>")
        first = harness_recursion.step(self.work(Script(compose=with_facts)), base_outputs=[OUTPUT])
        self.assertIn("memory", first.adopted_harness)
        current = library.current_overlay(1, "古装武侠")
        self.assertEqual(set(current), {"system_prompt", "skills"}, "facts verified on one project are wrong anchors for the next")
        self.assertIn("主角姓沈", library.context_block(1, "古装武侠"), "later proposers may still read them as an example")

        # The next project ran with that overlay; a composer that cuts one part of it leaves a smaller overlay.
        trimmed = "<notes>删除 -> skills -> 两次产出都没有用到</notes><harness><skills></skills></harness>"
        script = Script(inv=KEEP, dom="<harness><guardrails>不写旁白</guardrails></harness>", compose=trimmed)
        second = harness_recursion.step(self.work(script, task_id="task-0002", base_harness=current), base_outputs=[OUTPUT])
        proposer_saw = next(material for kind, _mission, material in script.missions if kind == "INV")
        self.assertIn("<system_prompt>先列分集钩子再写正文</system_prompt>", proposer_saw.split(prompts.says("context", "current"))[1])
        self.assertEqual(second.adopted_harness, {"system_prompt": "先列分集钩子再写正文"})
        self.assertEqual(library.current_overlay(1, "古装武侠"), {"system_prompt": "先列分集钩子再写正文"})

    def test_a_list_of_machine_checks_is_validated_run_on_each_output_and_read_in_words_by_the_agent(self):
        script_text = "max_chars: 100\ninclude: 分集钩子\nexclude：旁白\nmin_count: 钩子 | 2"
        self.assertEqual([check.kind for check in checks.parse(script_text)], ["max_chars", "include", "exclude", "min_count"])
        for unreadable in ("run: rm -rf /", "max_chars: 很多", "min_count: 钩子", "include: " + "长" * 80, "\n".join(f"include: 词{n}" for n in range(11))):
            with self.assertRaises(checks.CheckError, msg=unreadable):
                checks.parse(unreadable)
        with self.assertRaises(surface.ProposalError):
            surface.validate({"scripts": "import os"})
        with self.assertRaises(surface.ProposalError):
            surface.validate({"skills": "- 当有打戏时：写清谁先出手\n- 把人物关系写清楚"})
        surface.validate({"skills": "- 当有打戏时：写清谁先出手\n  出手前先交代站位\n- 若没有台词，写清环境声"})

        block = surface.render({"scripts": script_text})
        self.assertIn("全文不超过 100 字", block)
        self.assertNotIn("max_chars", block, "the grammar is for the engine; the agent reads the list in words")

        with_checks = MERGED.replace("</harness>", f"<scripts>{script_text}</scripts></harness>")
        script = Script(compose=with_checks)
        record = harness_recursion.step(self.work(script), base_outputs=[OUTPUT], remember=False)
        self.assertEqual(record.adopted_harness["scripts"], script_text)
        observed = record.result.rollouts["agg1"].observations
        self.assertIn("核对清单 4 条", observed)
        self.assertIn("超过 100 字", observed)
        self.assertEqual(record.result.rollouts["inv1"].observations, "", "an overlay with no list has nothing to report")
        reflector_saw = next(material for kind, _mission, material in script.missions if kind == "REFLECT")
        self.assertIn("超过 100 字", reflector_saw)
        chooser_saw = next(material for kind, _mission, material in script.missions if kind == "SELECT")
        self.assertNotIn("核对清单", chooser_saw)

    def test_a_kind_that_runs_with_an_overlay_is_checked_against_having_none_and_rolled_back_when_none_wins(self):
        first = harness_recursion.step(self.work(Script()), base_outputs=[OUTPUT])
        self.assertTrue(first.applied)
        self.assertNotIn("bare1", first.result.rollouts, "a kind with no overlay has nothing to be checked against")
        current = library.current_overlay(1, "古装武侠")

        # The next project ran with it. Its study also runs the call bare; the blind choice goes to that output.
        class BareWins(Script):
            def improver(self, mission, material):
                if self.kind(mission) == "SELECT":
                    with self.lock:
                        self.missions.append(("SELECT", mission, material))
                    blocks = material.split("## 候选 ")[1:]
                    return "<why>没带任何约定的那一份最贴合请求</why>\n```choice\n" + next(b.split()[0] for b in blocks if b.strip().endswith(OUTPUT[-20:]) and "改过的产出" not in b) + "\n```"
                return super().improver(mission, material)

        script = BareWins(dom="<harness><guardrails>不写旁白</guardrails></harness>", compose="<harness><guardrails>不写旁白</guardrails></harness>")
        base_output = "改过的产出：现有配置。" + OUTPUT
        second = harness_recursion.step(self.work(script, task_id="task-0002", base_harness=current), base_outputs=[base_output])
        self.assertIn("bare1", second.result.rollouts)
        self.assertEqual(script.executed.count(""), 1, "one run with no overlay at all")
        self.assertEqual(len(second.result.ledger.rollouts), 4, "the control is outside the 4k budget")
        self.assertEqual(second.adopted, "bare1")
        self.assertEqual(second.rolled_back, 1)
        self.assertEqual(second.adopted_harness, {})
        self.assertFalse(second.applied)
        self.assertEqual(library.current_overlay(1, "古装武侠"), {}, "the kind runs bare again")
        self.assertEqual(library.overlay_block(1, "古装武侠"), "")
        reflector_saw = next(material for kind, _mission, material in script.missions if kind == "REFLECT")
        self.assertIn(prompts.says("context", "bare_notes"), reflector_saw)
        summary = library.summarise([first.to_dict(), second.to_dict()])
        self.assertEqual(
            {key: summary["by_stage"]["1"][key] for key in ("studies", "edit_won", "rolled_back", "applied", "edit_win_rate")},
            {"studies": 2, "edit_won": 1, "rolled_back": 1, "applied": 1, "edit_win_rate": 0.5},
        )

    def test_the_stage_s_lens_yardstick_and_meaning_of_correct_reach_the_right_missions(self):
        script = Script()
        harness_recursion.step(
            self.work(script, lens="这份方案是三方共用的开工依据", yardstick="先抄清单再动笔", checks="请求点名的部分齐全"),
            base_outputs=[OUTPUT], remember=False,
        )
        seen = {kind: mission for kind, mission, _material in script.missions}
        for kind in ("INV", "DOM", "COMPOSE", "SELECT", "REFLECT"):
            self.assertIn("这份方案是三方共用的开工依据", seen[kind], kind)
        self.assertIn("先抄清单再动笔", seen["COMPOSE"])
        self.assertNotIn("先抄清单再动笔", seen["SELECT"])
        self.assertIn("请求点名的部分齐全", seen["SELECT"])
        self.assertNotIn("请求点名的部分齐全", seen["INV"], "what counts as correct is the selector's to apply, not a target to write toward")

    def test_a_project_s_own_names_stay_in_its_memory_and_never_reach_another_project(self):
        names = ["沈磨", "雷九斤"]
        with self.assertRaises(surface.ProposalError) as refused:
            surface.validate({"guardrails": "不得对调沈磨画左、雷九斤画右的站位", "scripts": "include: 沈磨"}, names)
        self.assertIn("沈磨", str(refused.exception))
        surface.validate({"memory": "本项目里沈磨恒在画左、雷九斤恒在画右", "guardrails": "不得对调两人已定的左右站位"}, names)

        # A proposal that names the cast outside memory is sent back with the reason; the rewrite is taken.
        named = "<harness><guardrails>不得对调沈磨画左的站位</guardrails></harness>"
        moved = "<harness><guardrails>不得对调已定的左右站位</guardrails><memory>本项目里沈磨恒在画左</memory></harness>"
        script = Script(inv=[named, moved], dom=KEEP, compose=moved)
        record = harness_recursion.step(self.work(script, project_terms=names), base_outputs=[OUTPUT])
        self.assertEqual(record.result.stage("inv1").attempts, 2)
        retry = [mission for kind, mission, _material in script.missions if kind == "INV"][1]
        self.assertIn("本项目的专有名词「沈磨」", retry)
        self.assertTrue(record.applied)
        self.assertIn("沈磨", record.adopted_harness["memory"])
        self.assertEqual(library.current_overlay(1, "古装武侠"), {"guardrails": "不得对调已定的左右站位"})

        # An overlay stored before the rule, or whose project named someone only later: the line stays behind.
        old = {"guardrails": "- 不写旁白\n- 不得让雷九斤换手", "scripts": "include: 沈磨\nmax_chars: 8000", "memory": "本项目里……", "skills": "当沈磨入画时：先写左眉断疤"}
        self.assertEqual(surface.carried(old, names), {"guardrails": "- 不写旁白", "scripts": "max_chars: 8000"})
        self.assertEqual(surface.carried(old), {key: value for key, value in old.items() if key != "memory"})

    def test_every_mission_says_what_the_improver_does_not_have(self):
        missions = [
            prompts.propose("INV", work="w", domain="d", k=1, index=1), prompts.propose("DOM", work="w", domain="d", k=2, index=2, round_t=2),
            prompts.compose(work="w", domain="d", k=2, base_count=2), prompts.compose(work="w", domain="d", k=2, base_count=2, round_t=1),
            prompts.select(work="w", downstream="x", count=3), prompts.reflect(work="w"),
        ]
        for mission in missions:
            self.assertIn(prompts.says("blocks", "answer_free"), mission)
            self.assertIn(prompts.says("blocks", "evidence_boundary"), mission)
            self.assertNotIn("{", mission.replace("{count}", ""), "every placeholder is filled")
        with self.assertRaises(ValueError):
            prompts.propose("XYZ", work="w", domain="d", k=1, index=1)


if __name__ == "__main__":
    unittest.main()
