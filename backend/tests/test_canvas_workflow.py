# -*- coding: utf-8 -*-
"""Canvas workflows: a plan is checked against what the canvas accepts, goes on as one version, and resumes without rerunning what worked."""

import json
import unittest

from app.core import canvas_workflow, studio_canvas
from app.core.canvas_workflow import WorkflowPlan
from tests.test_canvas_tools import CanvasToolRunCase
from tests.test_canvas_workspace import _node


def _plan(*steps, title="雨夜追车"):
    return {"title": title, "summary": "", "steps": list(steps)}


def _image(ref="frame", **extra):
    return {"ref": ref, "kind": "image_gen", "label": "首帧", "prompt": "雨夜街道", **extra}


def _video(ref="clip", source="frame", **extra):
    return {"ref": ref, "kind": "video_gen", "label": "追车", "prompt": "车冲出巷口", "inputs": [{"source": source, "role": "first_frame"}], **extra}


def _problems(*steps, existing=()):
    return canvas_workflow.validate_plan(WorkflowPlan.model_validate(_plan(*steps)), existing=existing)


def _codes(*steps, existing=()):
    return {item["code"] for item in _problems(*steps, existing=existing)}


class ValidationTests(unittest.TestCase):
    def test_a_sound_plan_has_no_problems(self):
        self.assertEqual(_problems(_image(), _video()), [])

    def test_text_only_video_is_refused(self):
        self.assertIn("no_reference", _codes({"ref": "clip", "kind": "video_gen", "prompt": "车"}))

    def test_a_note_can_give_a_video_its_words_but_not_its_picture(self):
        note = {"ref": "words", "kind": "note", "text": "车冲出巷口"}
        video = {"ref": "clip", "kind": "video_gen", "inputs": [{"source": "words"}]}
        self.assertEqual(_codes(note, video), {"no_reference"})

    def test_unknown_inputs_self_and_cycles_are_caught(self):
        self.assertIn("unknown_input", _codes(_video(source="nope")))
        self.assertIn("self", _codes({"ref": "a", "kind": "image_gen", "prompt": "x", "inputs": [{"source": "a"}]}))
        looped = (
            {"ref": "a", "kind": "tool", "tool": "enhance", "inputs": [{"source": "b"}]},
            {"ref": "b", "kind": "tool", "tool": "enhance", "inputs": [{"source": "a"}]},
        )
        self.assertIn("cycle", _codes(*looped))

    def test_a_continued_part_counts_the_clip_before_it_as_its_picture(self):
        second = {"ref": "part2", "kind": "video_gen", "prompt": "接着跑", "inputs": [{"source": "clip", "role": "continue_from"}]}
        self.assertEqual(_problems(_image(), _video(), second), [])
        self.assertIn("continue_from", canvas_workflow.planning_prompt("x"))

    def test_repeated_refs_are_caught(self):
        self.assertIn("duplicate_ref", _codes(_image(), _image()))

    def test_a_connection_the_canvas_would_refuse_is_refused_here(self):
        video_tool = {"ref": "t", "kind": "tool", "tool": "video_erase", "inputs": [{"source": "frame"}]}
        self.assertIn("bad_connection", _codes(_image(), video_tool))

    def test_a_role_that_does_not_apply_is_refused(self):
        self.assertIn("bad_connection", _codes(_image(), {"ref": "t", "kind": "tool", "tool": "enhance", "inputs": [{"source": "frame", "role": "first_frame"}]}))

    def test_tools_are_checked_for_what_they_need(self):
        self.assertIn("tool", _codes({"ref": "t", "kind": "tool", "tool": "nope"}))
        self.assertIn("no_image", _codes({"ref": "t", "kind": "tool", "tool": "enhance"}))
        self.assertIn("no_video", _codes({"ref": "t", "kind": "tool", "tool": "video_erase"}))
        self.assertIn("no_image", _codes(_image(), {"ref": "t", "kind": "tool", "tool": "set_background", "inputs": [{"source": "frame"}]}))
        self.assertIn("params", _codes(_image(), {"ref": "t", "kind": "tool", "tool": "style_transfer", "inputs": [{"source": "frame"}]}))
        self.assertEqual(_codes(_image(), {"ref": "t", "kind": "tool", "tool": "style_transfer", "params": {"style": "noir"}, "inputs": [{"source": "frame"}]}), set())

    def test_text_wired_into_a_tool_counts_as_its_words(self):
        note = {"ref": "words", "kind": "note", "text": "林夏回到老宅"}
        self.assertEqual(_codes(note, {"ref": "t", "kind": "tool", "tool": "beat_plan", "inputs": [{"source": "words"}]}), set())

    def test_a_media_step_says_what_it_waits_for(self):
        self.assertIn("medium", _codes({"ref": "m", "kind": "media"}))
        self.assertEqual(_codes({"ref": "m", "kind": "media", "medium": "video"}, {"ref": "t", "kind": "tool", "tool": "frame_extract", "inputs": [{"source": "m"}]}), set())

    def test_recipes_are_checked_and_stand_in_for_a_prompt(self):
        self.assertIn("recipe", _codes({"ref": "a", "kind": "image_gen", "recipe": "nope"}))

    def test_a_node_already_on_the_canvas_can_be_an_input(self):
        existing = [_node("old", "media", medium="image", output={"medium": "image", "url": "/media/a.png"})]
        self.assertEqual(_problems(_video(source="node:old"), existing=existing), [])
        self.assertIn("unknown_input", _codes(_video(source="node:gone"), existing=existing))

    def test_a_plan_that_is_too_long_does_not_parse(self):
        with self.assertRaises(ValueError):
            WorkflowPlan.model_validate(_plan(*[_image(f"s{index}") for index in range(canvas_workflow.MAX_STEPS + 1)]))

    def test_the_prompt_offers_the_real_catalog(self):
        prompt = canvas_workflow.planning_prompt("雨夜追车")
        self.assertIn("frame_extract", prompt)
        self.assertIn("ink_wash", prompt)
        self.assertIn("雨夜追车", prompt)


class CompileTests(unittest.TestCase):
    def compile(self, *steps, **kwargs):
        return canvas_workflow.compile_operations(WorkflowPlan.model_validate(_plan(*steps)), **kwargs)

    def test_it_applies_cleanly_as_one_document_change(self):
        document, refs = studio_canvas.apply_operations({"nodes": [], "edges": []}, self.compile(_image(), _video()))
        self.assertEqual(set(refs), {"frame", "clip"})
        self.assertEqual(document["edges"][0]["payload"]["role"], "first_frame")

    def test_later_steps_are_further_right_and_siblings_do_not_overlap(self):
        document, refs = studio_canvas.apply_operations({"nodes": [], "edges": []}, self.compile(_image(), _video("a"), _video("b")))
        nodes = {node["id"]: node for node in document["nodes"]}
        frame, a, b = nodes[refs["frame"]], nodes[refs["a"]], nodes[refs["b"]]
        self.assertGreaterEqual(a["x"], frame["x"] + frame["width"])
        self.assertEqual(a["x"], b["x"])
        self.assertGreaterEqual(b["y"], a["y"] + a["height"])

    def test_tool_params_and_media_kinds_survive(self):
        document, refs = studio_canvas.apply_operations({"nodes": [], "edges": []}, self.compile(
            {"ref": "m", "kind": "media", "medium": "video"},
            {"ref": "t", "kind": "tool", "tool": "video_erase", "params": {"x": 5}, "inputs": [{"source": "m"}]},
        ))
        nodes = {node["id"]: node for node in document["nodes"]}
        self.assertEqual(nodes[refs["m"]]["payload"]["medium"], "video")
        self.assertEqual(nodes[refs["t"]]["payload"]["params"], {"x": 5, "tool": "video_erase"})

    def test_a_recipe_is_rendered_into_the_prompt(self):
        from app.core import recipe_catalog

        recipe = next(item for item in recipe_catalog.catalog().describe()["recipes"] if not any(field.get("choices") for field in item["inputs"]))
        inputs = {item["name"]: "雨夜" for item in recipe["inputs"]}
        operations = self.compile({"ref": "a", "kind": "image_gen", "recipe": recipe["id"], "recipe_inputs": inputs})
        self.assertEqual(operations[0]["prompt"], recipe_catalog.render(recipe["id"], inputs)["prompt"])

    def test_it_can_read_from_a_node_already_there(self):
        existing = [_node("old", "media", medium="image", output={"medium": "image", "url": "/media/a.png"})]
        document, _ = studio_canvas.apply_operations({"nodes": existing, "edges": []}, self.compile(_video(source="node:old")))
        self.assertEqual(document["edges"][0]["source"], "old")


class StateTests(unittest.TestCase):
    def test_a_step_reads_from_the_canvas_and_its_runs(self):
        step = {"kind": "image_gen"}
        node = {"id": "n", "payload": {}}
        state = canvas_workflow.step_state
        self.assertEqual(state(step, None, None, False), "removed")
        self.assertEqual(state(step, node, None, False), "pending")
        self.assertEqual(state(step, node, {"status": "done"}, True), "done")
        self.assertEqual(state(step, node, {"status": "done"}, False), "pending")
        self.assertEqual(state(step, node, {"status": "failed"}, False), "failed")
        self.assertEqual(state({"kind": "media"}, node, None, False), "waiting_input")
        self.assertEqual(state({"kind": "media"}, {"payload": {"output": {"url": "x"}}}, None, False), "done")
        self.assertEqual(state({"kind": "note"}, node, None, False), "done")

    def test_the_whole_run_says_what_a_person_is_waiting_on(self):
        whole = canvas_workflow.overall_state
        self.assertEqual(whole(["done", "running", "failed"]), "running")
        self.assertEqual(whole(["done", "failed", "skipped"]), "failed")
        self.assertEqual(whole(["waiting_input", "pending"]), "needs_input")
        self.assertEqual(whole(["done", "pending"]), "ready")
        self.assertEqual(whole(["done", "removed"]), "done")


class WorkflowRouteTests(CanvasToolRunCase):
    def setUp(self):
        super().setUp()
        self.workflows = f"{self.base}/canvas/workflows"
        self.gateway.call_llm = self._call_llm
        self.gateway.llm_replies = []
        self.gateway.llm_calls = []

    def _call_llm(self, model, system, prompt, title, **kwargs):
        self.gateway.llm_calls.append(prompt)
        return self.gateway.llm_replies.pop(0)

    def create(self, *steps):
        response = self.client.post(self.workflows, json={"brief": "雨夜追车", "plan": _plan(*steps)})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def apply(self, workflow):
        response = self.client.post(f"{self.workflows}/{workflow['id']}/apply", json={})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def canvas(self):
        return self.client.get(f"{self.base}/canvas").json()

    def test_a_brief_becomes_a_draft_and_the_canvas_is_untouched(self):
        self.gateway.llm_replies = [json.dumps(_plan(_image(), _video()), ensure_ascii=False)]
        response = self.client.post(f"{self.workflows}/plan", json={"brief": "雨夜追车的预告"})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual((body["state"], body["can_apply"]), ("draft", True))
        self.assertIn("雨夜追车的预告", self.gateway.llm_calls[0])
        self.assertEqual(self.canvas()["nodes"], [])
        self.assertEqual(self.gateway.image_calls, [])

    def test_a_plan_the_canvas_would_refuse_goes_back_to_the_model_with_the_reason(self):
        self.gateway.llm_replies = [
            json.dumps(_plan({"ref": "clip", "kind": "video_gen", "prompt": "车"}), ensure_ascii=False),
            json.dumps(_plan(_image(), _video()), ensure_ascii=False),
        ]
        response = self.client.post(f"{self.workflows}/plan", json={"brief": "雨夜追车"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(len(self.gateway.llm_calls), 2)
        self.assertIn("纯文生视频", self.gateway.llm_calls[1])

    def test_a_model_that_never_gets_it_right_is_a_readable_refusal(self):
        self.gateway.llm_replies = ["不好意思"] * 3
        response = self.client.post(f"{self.workflows}/plan", json={"brief": "雨夜追车"})
        self.assertEqual(response.status_code, 422)
        self.assertIn("没有给出能用的流程", response.json()["detail"])
        self.assertEqual(self.client.get(self.workflows).json()["workflows"], [])

    def test_a_handwritten_plan_with_a_problem_is_kept_but_cannot_be_applied(self):
        workflow = self.create({"ref": "clip", "kind": "video_gen", "prompt": "车"})
        self.assertFalse(workflow["can_apply"])
        response = self.client.post(f"{self.workflows}/{workflow['id']}/apply", json={})
        self.assertEqual(response.status_code, 422)
        self.assertIn("纯文生视频", response.json()["detail"])
        self.assertEqual(self.canvas()["nodes"], [])

    def test_a_malformed_plan_is_refused_with_where_it_went_wrong(self):
        response = self.client.post(self.workflows, json={"plan": {"title": "x", "steps": [{"ref": "a", "kind": "script"}]}})
        self.assertEqual(response.status_code, 422)
        self.assertIn("kind", response.json()["detail"])

    def test_correcting_a_draft_rechecks_it(self):
        workflow = self.create({"ref": "clip", "kind": "video_gen", "prompt": "车"})
        response = self.client.put(f"{self.workflows}/{workflow['id']}", json={"plan": _plan(_image(), _video())})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["can_apply"])

    def test_applying_adds_every_step_in_one_version_and_runs_nothing(self):
        before = self.canvas()["version"]
        applied = self.apply(self.create(_image(), _video()))
        canvas = self.canvas()
        self.assertEqual(canvas["version"], before + 1)
        self.assertEqual(len(canvas["nodes"]), 2)
        self.assertEqual(len(canvas["edges"]), 1)
        self.assertEqual(self.gateway.image_calls, [])
        self.assertEqual(applied["state"], "ready")
        self.assertEqual(len(applied["runnable"]), 2)

    def test_it_lands_beside_what_is_already_there(self):
        saved = self.put([_node("old", "note", text="旧")])
        self.assertEqual(saved["version"], 1)
        self.apply(self.create(_image()))
        nodes = {node["id"]: node for node in self.canvas()["nodes"]}
        added = next(node for key, node in nodes.items() if key != "old")
        self.assertGreater(added["x"], nodes["old"]["x"] + nodes["old"]["width"])

    def test_applying_twice_is_refused(self):
        workflow = self.create(_image())
        self.apply(workflow)
        response = self.client.post(f"{self.workflows}/{workflow['id']}/apply", json={})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(len(self.canvas()["nodes"]), 1)

    def test_a_stale_canvas_is_a_conflict_and_nothing_is_added(self):
        workflow = self.create(_image())
        response = self.client.post(f"{self.workflows}/{workflow['id']}/apply", json={"expected_version": 99})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.canvas()["nodes"], [])
        self.assertFalse(self.client.get(f"{self.workflows}/{workflow['id']}").json()["applied"])

    def test_a_node_a_draft_read_from_may_have_gone_by_the_time_it_is_applied(self):
        self.put([_node("old", "media", medium="image", output={"medium": "image", "url": "/media/a.png"})])
        workflow = self.create(_video(source="node:old"))
        self.assertTrue(workflow["can_apply"])
        self.put([], expected=1)
        response = self.client.post(f"{self.workflows}/{workflow['id']}/apply", json={})
        self.assertEqual(response.status_code, 422)
        self.assertIn("node:old", response.json()["detail"])

    def test_someone_elses_project_is_not_found(self):
        workflow = self.create(_image())
        self.user = {"user_id": "stranger", "role": "user"}
        self.assertEqual(self.client.get(f"{self.workflows}/{workflow['id']}").status_code, 404)
        self.assertEqual(self.client.post(self.workflows, json={"plan": _plan(_image())}).status_code, 404)

    def run_step_nodes(self, node_ids, op):
        return self.run_nodes(node_ids, self.canvas()["version"], op=op)

    def test_a_failure_stops_what_depends_on_it_and_a_retry_runs_only_what_did_not_finish(self):
        applied = self.apply(self.create(
            _image("a"), {"ref": "b", "kind": "tool", "tool": "enhance", "inputs": [{"source": "a"}]},
            {"ref": "c", "kind": "tool", "tool": "enhance", "inputs": [{"source": "b"}]},
        ))
        ids = {step["ref"]: step["node_id"] for step in applied["steps"]}
        real = self.gateway.generate_image
        calls = []

        def flaky(model, prompt, **kwargs):
            calls.append(prompt)
            if len(calls) == 2 and self.fail_second:
                raise RuntimeError("供应商超时")
            return real(model, prompt, **kwargs)

        self.fail_second = True
        self.gateway.generate_image = flaky
        self.assertEqual(self.run_step_nodes(applied["runnable"], "first")["status"], "started")
        status = self.client.get(f"{self.workflows}/{applied['id']}").json()
        states = {step["ref"]: step["state"] for step in status["steps"]}
        self.assertEqual(states["a"], "done")
        self.assertEqual(states["b"], "failed")
        self.assertIn(states["c"], {"skipped", "cancelled"})
        self.assertEqual(status["state"], "failed")
        self.assertIn("供应商超时", next(step for step in status["steps"] if step["ref"] == "b")["error"])
        self.assertEqual(set(status["runnable"]), {ids["b"], ids["c"]})

        self.fail_second = False
        spent = len(calls)
        self.assertEqual(self.run_step_nodes(status["runnable"], "second")["status"], "started")
        final = self.client.get(f"{self.workflows}/{applied['id']}").json()
        self.assertEqual(final["state"], "done")
        self.assertEqual(final["runnable"], [])
        # Two steps were left, so two more calls: the one that had worked was not paid for again.
        self.assertEqual(len(calls), spent + 2)

    def test_a_step_waiting_on_an_upload_holds_the_run_with_a_reason(self):
        applied = self.apply(self.create(
            {"ref": "m", "kind": "media", "medium": "video", "label": "原片"},
            {"ref": "t", "kind": "tool", "tool": "audio_extract", "inputs": [{"source": "m"}]},
        ))
        self.assertEqual(applied["state"], "needs_input")
        answer = self.run_step_nodes(applied["runnable"], "wait")
        self.assertEqual(answer["status"], "blocked")
        messages = " ".join(item["message"] for row in answer["assessment"]["nodes"] for item in row["problems"])
        self.assertIn("还没有结果", messages)

    def test_deleting_a_step_from_the_canvas_is_noticed(self):
        applied = self.apply(self.create(_image("a"), _image("b")))
        keep = next(step["node_id"] for step in applied["steps"] if step["ref"] == "a")
        canvas = self.canvas()
        self.put([node for node in canvas["nodes"] if node["id"] == keep], expected=canvas["version"])
        status = self.client.get(f"{self.workflows}/{applied['id']}").json()
        self.assertEqual({step["ref"]: step["state"] for step in status["steps"]}, {"a": "pending", "b": "removed"})
        self.assertEqual(status["runnable"], [keep])

    def test_forgetting_a_workflow_leaves_its_nodes(self):
        applied = self.apply(self.create(_image()))
        self.assertEqual(self.client.delete(f"{self.workflows}/{applied['id']}").status_code, 200)
        self.assertEqual(self.client.get(self.workflows).json()["workflows"], [])
        self.assertEqual(len(self.canvas()["nodes"]), 1)
        self.assertEqual(self.client.get(f"{self.workflows}/{applied['id']}").status_code, 404)

    def test_workflows_belong_to_their_board(self):
        self.create(_image())
        board = self.client.post(f"{self.base}/canvases", json={"title": "二"}).json()["id"]
        self.assertEqual(self.client.get(self.workflows, params={"canvas_id": board}).json()["workflows"], [])
        self.assertEqual(len(self.client.get(self.workflows).json()["workflows"]), 1)


class AgentWorkflowTests(WorkflowRouteTests):
    def call(self, name, **arguments):
        from unittest.mock import patch

        from app.core.agent_tools import catalog

        with patch("app.api.studio_api.get_studio_service", return_value=self.studio):
            return catalog.call(name, {"task_id": "t-1", **arguments}, service=self.drama, user=self.user)

    def test_planning_waits_for_confirmation_applying_does_not_spend_and_status_gives_what_to_run(self):
        waiting = self.call("plan_canvas_workflow", brief="雨夜追车")
        self.assertTrue(waiting["needs_confirmation"])
        self.gateway.llm_replies = [json.dumps(_plan(_image(), _video()), ensure_ascii=False)]
        planned = self.call("plan_canvas_workflow", brief="雨夜追车", confirm=True)
        self.assertTrue(planned["ok"], planned)
        workflow = planned["result"]["id"]
        applied = self.call("apply_canvas_workflow", workflow_id=workflow)
        self.assertTrue(applied["ok"], applied)
        self.assertEqual(self.gateway.image_calls, [])
        status = self.call("canvas_workflow_status", workflow_id=workflow)
        self.assertEqual(len(status["result"]["runnable"]), 2)


if __name__ == "__main__":
    unittest.main()
