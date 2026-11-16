"""The background study of a stage call: when it starts, what it may touch, and what it leaves behind."""

import inspect
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import llm_profile, usage_ledger
from app.core.harness_recursion import harness as surface
from app.core.harness_recursion import library, prompts
from app.service import drama_service, harness_evolution
from tests.test_harness_recursion import EXPERIENCE, OUTPUT, Script

SYSTEM = "你是总导演。\n【黄金叙事结构】：……\n【题材结构指导】：……\n"
REQUEST = "请为短剧《刀不认人》做导演方案定调与三幕大纲规划。"
NEW_RULE = "<notes>新增 -> guardrails -> 产出里出现了旁白</notes><harness><guardrails>不写旁白</guardrails></harness>"


class Gateway:
    """Stands where ModelGateway stands: the improving model is the script, and it can be 'offline'."""

    def __init__(self, script: Script, *, offline: bool = False, has_model: bool = True, die_at: int = 0):
        self.script, self.offline, self.has_model, self.die_at = script, offline, has_model, die_at
        self.purposes: list[str | None] = []
        self.models: list[str] = []
        # The stage's own call made again: the system prompt it was given, and everything else it was called with.
        self.systems: list[str] = []
        self.stage_calls: list[tuple] = []
        self.calls = 0

    def call_llm(self, model, system_prompt, user_prompt, creative_title, *args, **kwargs):
        self.calls += 1
        if self.die_at and self.calls >= self.die_at:
            raise KeyboardInterrupt("the server stopped")
        self.purposes.append(usage_ledger._current_purpose.get())
        if prompts.says("blocks", "answer_free") in system_prompt:
            self.models.append(model)
            return self.script.improver(system_prompt, user_prompt)
        self.systems.append(system_prompt)
        self.stage_calls.append((model, user_prompt, creative_title, args, kwargs, llm_profile.current_reasoning()))
        return self.script.execute(system_prompt[len(SYSTEM):].strip())

    def last_answer_was_offline(self) -> bool:
        return self.offline

    def has_text_model(self) -> bool:
        return self.has_model


class StudyStageTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        for patcher in (
            patch.object(library, "LIBRARY_ROOT", Path(folder.name)),
            patch.dict(os.environ, {key: value for key, value in os.environ.items() if not key.startswith("HARNESS_EVOLUTION")}, clear=True),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.script = Script()

    def study(self, gateway: Gateway, **overrides) -> bool:
        values = dict(
            task_id="task-0001", stage=1, domain="古装武侠", model="deepseek-flash", title="刀不认人",
            system_prompt=SYSTEM, request=REQUEST, output=OUTPUT, director_style="写实", shot_style="cinematic", guidance="多写江湖气", wait=True,
        )
        return harness_evolution.study_stage(gateway, **{**values, **overrides})

    def test_a_studied_stage_leaves_a_lesson_for_the_next_project_of_its_kind(self):
        gateway = Gateway(self.script)
        self.assertEqual(harness_evolution.overlay_for(1, "古装武侠"), "")
        self.assertTrue(self.study(gateway))
        # Three runs of the stage's own call, each with the fixed prompt untouched in front of the overlay.
        self.assertEqual(len(gateway.systems), 3)
        self.assertTrue(all(system.startswith(SYSTEM) and prompts.says("overlay", "header") in system for system in gateway.systems))
        # Each is the stage's call as the stage made it: same model, same request, same styles and guidance, no reasoning scope.
        self.assertEqual(
            set((model, user, title, args, tuple(kwargs.items()), level) for model, user, title, args, kwargs, level in gateway.stage_calls),
            {("deepseek-flash", REQUEST, "刀不认人", ("写实", "cinematic"), (("user_instruction", "多写江湖气"),), None)},
        )
        # Two proposals, one composition, the blind selection and the reflection.
        self.assertEqual(len(gateway.models), 5)
        self.assertEqual(set(gateway.purposes), {harness_evolution.PURPOSE}, "its calls are told apart from the stage's own in the usage ledger")
        self.assertIn("先列分集钩子再写正文", harness_evolution.overlay_for(1, "古装武侠"))
        self.assertEqual(harness_evolution.overlay_for(8, "古装武侠"), "")
        run = library.runs()[-1]
        self.assertEqual((run["adopted"], run["applied"], run["ledger"]["R"], run["ledger"]["P"]), ("agg1", True, 4, 3))
        self.assertEqual(harness_evolution.report()["kinds"][0]["applied"], 1)

    def test_an_adopted_overlay_can_be_taken_back_out(self):
        self.assertTrue(self.study(Gateway(self.script)))
        self.assertTrue(harness_evolution.overlay_for(1, "古装武侠"))
        self.assertFalse(harness_evolution.retire(1, "古装武侠", "no-such-task"))
        self.assertTrue(harness_evolution.retire(1, "古装武侠", "task-0001"))
        self.assertEqual(harness_evolution.overlay_for(1, "古装武侠"), "")
        kind = harness_evolution.report()["kinds"][0]
        self.assertEqual((kind["entries"], kind["applied"]), (1, 0), "the entry stays on record")

    def test_the_same_stage_call_is_not_studied_twice(self):
        gateway = Gateway(self.script)
        self.assertTrue(self.study(gateway))
        calls = len(gateway.models)
        self.assertFalse(self.study(gateway))
        self.assertEqual(len(gateway.models), calls)
        self.assertTrue(self.study(gateway, output=OUTPUT + "换了一版。"), "a new output is new evidence")

    def test_it_stays_out_of_the_way_when_off_unwanted_or_without_a_real_model(self):
        gateway = Gateway(self.script)
        with patch.dict(os.environ, {"HARNESS_EVOLUTION": "off"}):
            self.assertFalse(self.study(gateway))
            self.assertFalse(harness_evolution.wants(1))
        with patch.dict(os.environ, {"HARNESS_EVOLUTION_STAGES": "8"}):
            self.assertFalse(self.study(gateway))
        with patch.dict(os.environ, {"HARNESS_EVOLUTION_STAGES": "1,5"}):
            self.assertFalse(self.study(gateway, stage=5), "a stage nobody described the work of is not studied")
        self.assertFalse(self.study(gateway, output="  "))
        self.assertFalse(self.study(Gateway(self.script, offline=True)), "a template answer is not the agent's work")
        self.assertFalse(self.study(Gateway(self.script, has_model=False)))
        self.assertEqual(gateway.calls, 0)
        self.assertEqual(library.runs(), [])
        self.assertEqual(harness_evolution.pending_jobs(), [])

    def test_a_study_cut_short_goes_on_after_the_restart_without_paying_twice(self):
        # A whole study is eight calls: two proposals, three runs of the stage call, a composition, a selection, a reflection.
        whole = Gateway(Script())
        self.assertTrue(self.study(whole, task_id="reference", output=OUTPUT + "参照。"))
        self.assertEqual(whole.calls, 8)

        dying = Gateway(self.script, die_at=6)
        self.assertTrue(self.study(dying), "the stage itself never hears of it")
        self.assertEqual(len(library.runs()), 1)
        (job,) = harness_evolution.pending_jobs()
        self.assertEqual((job["task_id"], job["attempts"], len(job["memo"])), ("task-0001", 1, 5))
        self.assertFalse(self.study(Gateway(self.script)), "it is waiting to be resumed, not to be started again")

        after = Gateway(self.script)
        self.assertEqual(harness_evolution.resume_pending(after, wait=True), 1)
        self.assertEqual(after.calls, 3, "only what had not been answered before the restart is asked")
        self.assertEqual(harness_evolution.pending_jobs(), [])
        run = library.runs()[-1]
        self.assertEqual((run["task_id"], run["adopted"], run["applied"]), ("task-0001", "agg1", True))
        self.assertEqual({key: run["spent"][key] for key in ("replayed", "attempts")}, {"replayed": 5, "attempts": 2})
        self.assertEqual(harness_evolution.resume_pending(after, wait=True), 0)

    def test_a_study_that_can_never_finish_is_given_up(self):
        for attempt in range(harness_evolution.MAX_ATTEMPTS):
            dying = Gateway(self.script, die_at=1)
            started = self.study(dying) if attempt == 0 else harness_evolution.resume_pending(dying, wait=True)
            self.assertTrue(started)
        self.assertEqual(harness_evolution.pending_jobs()[0]["attempts"], harness_evolution.MAX_ATTEMPTS)
        self.assertEqual(harness_evolution.resume_pending(Gateway(self.script), wait=True), 0)
        self.assertEqual(harness_evolution.pending_jobs(), [])
        with patch.dict(os.environ, {"HARNESS_EVOLUTION": "off"}):
            self.assertEqual(harness_evolution.resume_pending(Gateway(self.script), wait=True), 0)

    def test_an_answer_from_the_offline_template_mid_study_is_not_taken_as_evidence(self):
        gateway = Gateway(self.script)
        original = gateway.call_llm

        def call(*args, **kwargs):
            gateway.offline = True
            return original(*args, **kwargs)

        gateway.call_llm = call
        self.assertTrue(self.study(gateway))
        self.assertEqual(gateway.systems, [], "no proposal was accepted, so nothing was run under one")
        self.assertEqual(library.entries(1, "古装武侠"), [])

    def test_budget_and_model_come_from_the_environment(self):
        self.assertEqual(harness_evolution.budget(), (1, "agg"))
        self.assertEqual(harness_evolution.stages(), frozenset({1, 3, 4, 8}))
        with patch.dict(os.environ, {"HARNESS_EVOLUTION_K": "9", "HARNESS_EVOLUTION_RECURSION": "sequential", "HARNESS_EVOLUTION_MODEL": "improver-x", "HARNESS_EVOLUTION_STAGES": "1"}):
            self.assertEqual(harness_evolution.budget(), (3, "seq"))
            gateway = Gateway(Script(reflect=EXPERIENCE.format(confidence="medium")))
            self.assertTrue(self.study(gateway))
            self.assertEqual(set(gateway.models), {"improver-x"})
            self.assertEqual(library.runs()[-1]["ledger"], {**library.runs()[-1]["ledger"], "mode": "seq", "k": 3, "R": 12, "P": 9})

    def test_a_stage_that_ran_with_an_overlay_no_longer_current_is_not_studied(self):
        gateway = Gateway(self.script)
        self.assertTrue(self.study(gateway))
        block = harness_evolution.overlay_for(1, "古装武侠")
        stale = block.replace("先列分集钩子再写正文", "一版已经被换掉的约定")
        self.assertFalse(self.study(gateway, system_prompt=SYSTEM + stale, overlay_block=stale, output=OUTPUT + "新的一版。"))
        self.assertFalse(self.study(gateway, system_prompt=SYSTEM, overlay_block=block, output=OUTPUT + "新的一版。"), "the block is not in the prompt it claims to be in")
        gateway.systems.clear()
        # The next study proposes something the overlay does not have yet, so there is something to run.
        self.script.replies.update(DOM=NEW_RULE, COMPOSE=NEW_RULE)
        self.assertTrue(self.study(gateway, system_prompt=SYSTEM + block + "\n【创作类型】短剧\n", overlay_block=block, output=OUTPUT + "新的一版。"))
        self.assertTrue(gateway.systems and all(system.endswith("\n【创作类型】短剧\n") for system in gateway.systems), "the overlay is replaced where it stood")
        # The kind already ran with an overlay, so one of those runs carries none at all: the control.
        self.assertEqual(sum(1 for system in gateway.systems if prompts.says("overlay", "header") not in system), 1)

    def test_the_stage_s_own_checks_are_shown_beside_each_execution(self):
        checked: list[str] = []

        def problems(text: str) -> list[str]:
            checked.append(text)
            return [] if "改过的产出" in text else ["第 3 格与第 2 格景别相同", "入镜角色与画面对不上"]

        gateway = Gateway(self.script)
        self.assertTrue(self.study(gateway, stage=4, observe=problems, delivered=lambda text: "方案正文" in text))
        self.assertEqual(len(checked), 4, "the stage's output and each of the three executions under an overlay")
        composer_saw = next(material for kind, _mission, material in self.script.missions if kind == "COMPOSE")
        self.assertIn("第 3 格与第 2 格景别相同；入镜角色与画面对不上", composer_saw)
        self.assertIn(prompts.says("context", "observed_none"), composer_saw)
        chooser_saw = next(material for kind, _mission, material in self.script.missions if kind == "SELECT")
        self.assertNotIn("景别相同", chooser_saw, "selection compares the outputs alone")
        self.assertEqual(library.runs()[-1]["stage"], 4)

        # An output the stage could not use is not a candidate, whatever it says.
        self.script = Script()
        gateway = Gateway(self.script)
        self.assertTrue(self.study(gateway, stage=4, output=OUTPUT + "再来一版。", delivered=lambda text: "改过的产出" not in text))
        run = library.runs()[-1]
        self.assertEqual((run["adopted"], run["applied"]), ("base1", False))
        self.assertEqual(run["delivered"], {"base1": True, "inv1": False, "dom1": False, "agg1": False})

    def test_the_outline_names_what_the_fixed_prompt_already_covers(self):
        outline = harness_evolution.outline_of(SYSTEM)
        self.assertIn("黄金叙事结构", outline)
        self.assertIn("题材结构指导", outline)
        self.assertEqual(harness_evolution.outline_of("没有小节标题"), "")


class StageOneEndToEndTests(unittest.TestCase):
    """The real stage-1 code with a scripted model: the plan it stores is its own, the study runs beside it."""

    def setUp(self):
        from tests.test_screenwriting_pipeline import _service, _task

        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        for patcher in (
            patch.object(library, "LIBRARY_ROOT", Path(folder.name) / "library"),
            patch.dict(os.environ, {"QC_IN_BACKGROUND": "0", **{key: value for key, value in os.environ.items() if not key.startswith("HARNESS_EVOLUTION")}}, clear=True),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.script = Script()
        script, plan_calls = self.script, []
        self.plan_calls = plan_calls

        class StageGateway(Gateway):
            GENRE_TEMPLATES = drama_service.DramaService().gateway.GENRE_TEMPLATES

            def get_genre(self, title: str) -> str:
                return "mystery"

            def call_llm(self, model, system_prompt, user_prompt, creative_title, *args, **kwargs):
                if prompts.says("blocks", "answer_free") not in system_prompt:
                    # Not an improvement mission: the stage's own call, or the same call again under an overlay.
                    plan_calls.append(system_prompt)
                    overlay = system_prompt.split(prompts.says("overlay", "header"))
                    return script.execute(overlay[1].strip() if len(overlay) > 1 else "")
                return super().call_llm(model, system_prompt, user_prompt, creative_title, *args, **kwargs)

        self.repo = drama_service.TaskRepository(str(Path(folder.name) / "tasks.json"))
        self.repo.save_task("sw-task-1", _task())
        self.gateway = StageGateway(self.script)
        self.service = _service(self.gateway, self.repo)

    def _run_stage_one(self) -> dict:
        import asyncio
        import threading

        with patch.object(self.service, "run_real_consistency_check", return_value="QC-OK"):
            task = asyncio.run(self.service.execute_stage("sw-task-1", 1))
        for thread in threading.enumerate():
            if thread.name.startswith("harness-1-"):
                thread.join(10)
        return task

    def test_the_plan_is_the_stage_s_own_and_the_next_project_of_the_kind_reads_the_lesson(self):
        task = self._run_stage_one()
        self.assertEqual(task["assets"]["1"], OUTPUT, "the project that taught the lesson is not changed by it")
        # One call for the plan, then three under edited overlays; the fixed prompt is the same prefix in all four.
        self.assertEqual(len(self.plan_calls), 4)
        self.assertNotIn(prompts.says("overlay", "header"), self.plan_calls[0])
        self.assertTrue(all(call.startswith(self.plan_calls[0]) for call in self.plan_calls[1:]))
        run = library.runs()[-1]
        self.assertEqual((run["task_id"], run["stage"], run["adopted"], run["applied"]), ("sw-task-1", 1, "agg1", True))

        # The next project of the same kind: its stage prompt now carries the overlay, and its study edits it.
        self.plan_calls.clear()
        self.script.replies.update(DOM=NEW_RULE, COMPOSE=NEW_RULE)
        self.repo.save_task("sw-task-2", {**self.repo.get_task("sw-task-1"), "task_id": "sw-task-2", "current_stage": 1, "status": "idle", "assets": {}})
        import asyncio

        with patch.object(self.service, "run_real_consistency_check", return_value="QC-OK"):
            asyncio.run(self.service.execute_stage("sw-task-2", 1))
        for thread in __import__("threading").enumerate():
            if thread.name.startswith("harness-1-"):
                thread.join(10)
        self.assertIn("先列分集钩子再写正文", self.plan_calls[0])
        # Its own study edits that overlay where it stands: no prompt ever carries two of them.
        self.assertGreater(len(self.plan_calls), 1)
        headers = [call.count(prompts.says("overlay", "header")) for call in self.plan_calls]
        self.assertEqual(max(headers), 1)
        # One run carries no overlay at all: the control that tells whether the overlay in use is doing harm.
        self.assertEqual(headers.count(0), 1)
        self.assertEqual(headers[0], 1, "the stage's own call ran with the kind's overlay")
        self.assertEqual(library.runs()[-1]["task_id"], "sw-task-2")

    def test_switched_off_the_stage_makes_exactly_its_own_call(self):
        with patch.dict(os.environ, {"HARNESS_EVOLUTION": "off"}):
            task = self._run_stage_one()
        self.assertEqual(task["assets"]["1"], OUTPUT)
        self.assertEqual(len(self.plan_calls), 1)
        self.assertEqual(library.runs(), [])


class StageFourEndToEndTests(unittest.TestCase):
    """The real stage-4 code with scripted models: several scenes are drawn, one table call is studied."""

    def test_one_scene_s_table_is_studied_with_the_stage_s_own_checks_and_the_boards_are_untouched(self):
        import threading

        from tests import test_storyboard_scene_parallel as boards

        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        script, providers = Script(), boards._Providers(delay=0.001)
        table_prompts: list[tuple[str, str]] = []
        lock = threading.Lock()

        def llm(model, system, user, *args, **kwargs):
            if prompts.says("blocks", "answer_free") in system:
                return script.improver(system, user)
            with lock:
                table_prompts.append((boards.re.search(r"【场景编号】：(\S+)", user)[1], system))
            return providers.llm(model, system, user, *args, **kwargs)

        repo = drama_service.TaskRepository(str(Path(folder.name) / "tasks.json"))
        service = drama_service.DramaService()
        service.repo = repo
        task = boards._task("evolve-4")
        repo.save_task("evolve-4", task)
        environment = {key: value for key, value in os.environ.items() if not key.startswith("HARNESS_EVOLUTION")}
        with patch.dict(os.environ, environment, clear=True), \
                patch.object(library, "LIBRARY_ROOT", Path(folder.name) / "library"), \
                patch.object(service.gateway, "call_llm", side_effect=llm), \
                patch.object(service.gateway, "has_text_model", return_value=True), \
                patch.object(service.gateway, "last_answer_was_offline", return_value=False), \
                patch.object(service.gateway, "generate_image", side_effect=providers.image), \
                patch.object(service.gateway, "validate_image_request", create=True), \
                patch("app.service.drama_service.load_storyboard_elements", return_value=[]), \
                patch("app.service.drama_service.persist_storyboard_frame", return_value=None), \
                patch("app.service.drama_service.compose_nine_grid", lambda sources, path: path), \
                patch.object(drama_service.DramaService, "run_real_consistency_check", lambda _self, *a, **k: "OK"):
            service._execute_stage_blocking("evolve-4", 4, _claimed_task=task)
            for thread in threading.enumerate():
                if thread.name.startswith("harness-4-"):
                    thread.join(20)
            runs = library.runs()

        stored = repo.get_task("evolve-4")["assets"]["4_scene_boards"]
        self.assertTrue(all(stored[scene_id]["status"] == "done" for scene_id in boards.SCENE_IDS))
        self.assertEqual(len(runs), 1, "one scene a run is studied, however many are drawn")
        run = runs[0]
        self.assertEqual((run["stage"], run["ledger"]["R"], run["ledger"]["P"]), (4, 4, 3))
        self.assertEqual(run["delivered"], {"base1": True, "inv1": True, "dom1": True, "agg1": True}, "each execution parsed as a table")
        # The first scene in story order: its own table calls (a draft, and a revision when its checks ask for one),
        # then the same call three times with an overlay at the very end of the prompt.
        header = prompts.says("overlay", "header")
        studied = [system for scene_id, system in table_prompts if scene_id == boards.SCENE_IDS[0]]
        own = [system for system in studied if header not in system]
        probes = [system for system in studied if header in system]
        self.assertEqual(len(probes), 3)
        self.assertTrue(all(system.startswith(own[0]) and header in system[len(own[0]):] for system in probes))
        for other in boards.SCENE_IDS[1:]:
            theirs = [system for scene_id, system in table_prompts if scene_id == other]
            self.assertEqual(len(theirs), len(own), "the other scenes make only their own calls")
            self.assertFalse(any(header in system for system in theirs))
        # The improvers were shown what the stage's own table checks said about each execution.
        composer_saw = next(material for kind, _mission, material in script.missions if kind == "COMPOSE")
        self.assertIn("（对这份产出的机器检查）", composer_saw)


class WiringTests(unittest.TestCase):
    def test_the_text_stages_are_studied_and_run_with_their_kind_s_overlay(self):
        source = inspect.getsource(drama_service.DramaService._execute_stage_blocking)
        for stage in (1, 3, 8):
            self.assertIn(f"harness_evolution.overlay_for({stage}, show_cluster.name)", source)
            self.assertIn(f"task_id=task_id, stage={stage}, domain=show_cluster.name", source)
            self.assertIn("overlay_block=verified_block", source)
        self.assertEqual(source.count("harness_evolution.study_stage("), 3)
        # The storyboard table: the overlay is read once before the boards are drawn, and one scene a run is studied.
        self.assertIn("board_overlay = harness_evolution.overlay_for(4, board_domain)", source)
        self.assertIn("evolution=(board_domain, board_overlay) if scene_id == pending_ids[0] else None", source)
        board = inspect.getsource(drama_service.DramaService._generate_scene_board)
        self.assertEqual(board.count("harness_evolution.study_stage("), 1)
        self.assertIn("stage=4, domain=evolution[0]", board)
        self.assertIn("output=first_draft, overlay_block=evolution[1]", board)
        self.assertIn("observe=_table_problems", board)

    def test_every_studied_stage_has_its_work_described(self):
        for stage in sorted(harness_evolution.stages()):
            described = prompts.work_of(stage)
            self.assertTrue(all(described[key] for key in prompts.WORK_FIELDS), f"stage {stage}")
            self.assertIsNone(surface.grader_word(" ".join(described.values())), "words about the work, never about judging it")


if __name__ == "__main__":
    unittest.main()
