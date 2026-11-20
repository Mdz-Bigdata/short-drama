"""The infinite node canvas: unbounded coordinates, one level of group nesting, folding, and layout ops.

No model is called; everything here is geometry and document rules.
"""

import json
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.core import canvas_layout, studio_canvas
from app.core.agent_tools import catalog
from app.schema.studio import CanvasBookmark, CanvasNode, CanvasPutRequest
from tests.test_canvas_workspace import CanvasCase


def _node(node_id, kind="note", x=0.0, y=0.0, width=200.0, height=100.0, **payload):
    return {"id": node_id, "kind": kind, "track": "freezone", "x": x, "y": y, "width": width, "height": height, "artifact_id": None, "payload": payload}


def _apply(nodes, operations, edges=()):
    changed, refs = studio_canvas.apply_operations({"nodes": nodes, "edges": list(edges)}, operations)
    return {node["id"]: node for node in changed["nodes"]}, changed, refs


class CoordinateLimitTests(unittest.TestCase):
    def test_far_away_positions_and_huge_frames_are_fine(self):
        node = CanvasNode.model_validate(_node("far", x=-999_999_999.5, y=999_999_999, width=1_000_000, height=1_000_000))
        self.assertEqual(node.x, -999_999_999.5)
        for bad in ({"x": 1.5e9}, {"y": -2e9}, {"width": 1_000_001}, {"height": 0}):
            with self.assertRaises(ValidationError, msg=bad):
                CanvasNode.model_validate({**_node("n"), **bad})

    def test_nan_and_infinity_are_refused(self):
        for field in ("x", "y", "width", "height"):
            for bad in (float("nan"), float("inf"), float("-inf")):
                with self.assertRaises(ValidationError, msg=(field, bad)):
                    CanvasNode.model_validate({**_node("n"), field: bad})
        with self.assertRaises(ValidationError):
            CanvasBookmark.model_validate({"slot": 1, "x": float("nan"), "y": 0, "zoom": 1})

    def test_bookmarks_reach_far_and_zoom_stays_in_range(self):
        self.assertEqual(CanvasBookmark.model_validate({"slot": 1, "x": 9e9, "y": -1e10, "zoom": 0.01}).zoom, 0.01)
        for bad in ({"x": 1.1e10}, {"zoom": 0.009}, {"zoom": 16.5}, {"zoom": 0}):
            with self.assertRaises(ValidationError, msg=bad):
                CanvasBookmark.model_validate({"slot": 1, "x": 0, "y": 0, "zoom": 1, **bad})

    def test_node_and_edge_caps_are_raised(self):
        nodes = [_node(f"n{i}") for i in range(5000)]
        self.assertEqual(len(CanvasPutRequest(expected_version=0, nodes=nodes).nodes), 5000)
        with self.assertRaises(ValidationError):
            CanvasPutRequest(expected_version=0, nodes=[*nodes, _node("one-more")])
        edges = [{"id": f"e{i}", "source": "n0", "target": "n1", "kind": "reference"} for i in range(12001)]
        with self.assertRaises(ValidationError):
            CanvasPutRequest(expected_version=0, nodes=nodes[:2], edges=edges)

    def test_edit_ops_refuse_non_finite_geometry(self):
        for bad in (float("nan"), float("inf"), 2e9):
            with self.assertRaises(studio_canvas.CanvasOperationError):
                _apply([_node("a")], [{"op": "update_node", "id": "a", "x": bad}])
        moved, _, _ = _apply([_node("a")], [{"op": "update_node", "id": "a", "x": 5e8, "y": -5e8, "width": 900_000}])
        self.assertEqual((moved["a"]["x"], moved["a"]["y"], moved["a"]["width"]), (5e8, -5e8, 900_000))


class NestingTests(unittest.TestCase):
    def test_one_level_of_nesting_is_allowed(self):
        nodes = [_node("a", x=0, y=0), _node("b", x=300, y=0), _node("c", x=0, y=400)]
        by_id, changed, refs = _apply(nodes, [
            {"op": "group", "ref": "inner", "ids": ["a", "b"], "label": "里"},
            {"op": "group", "ref": "outer", "ids": ["inner", "c"], "label": "外"},
        ])
        inner, outer = by_id[refs["inner"]], by_id[refs["outer"]]
        self.assertEqual(by_id["a"]["payload"]["groupId"], inner["id"])
        self.assertEqual(inner["payload"]["groupId"], outer["id"])
        self.assertEqual(by_id["c"]["payload"]["groupId"], outer["id"])
        # The outer frame holds the inner one, and the outer group draws first.
        self.assertLessEqual(outer["x"], inner["x"])
        self.assertGreaterEqual(outer["x"] + outer["width"], inner["x"] + inner["width"])
        order = [node["id"] for node in changed["nodes"]]
        self.assertLess(order.index(outer["id"]), order.index(inner["id"]))
        CanvasPutRequest(expected_version=0, nodes=changed["nodes"])

    def test_a_group_can_be_made_inside_a_named_parent(self):
        nodes = [_node("g", "group", x=-100, y=-100, width=1000, height=800), _node("a"), _node("b", x=300)]
        by_id, _, refs = _apply(nodes, [{"op": "group", "ref": "sub", "ids": ["a", "b"], "parent": "g"}])
        self.assertEqual(by_id[refs["sub"]]["payload"]["groupId"], "g")
        # Grouping members of one group keeps the new group inside it.
        nodes = [_node("g", "group", x=-100, y=-100, width=1000, height=800), _node("a", groupId="g"), _node("b", x=300, groupId="g")]
        by_id, _, refs = _apply(nodes, [{"op": "group", "ref": "sub", "ids": ["a", "b"]}])
        self.assertEqual(by_id[refs["sub"]]["payload"]["groupId"], "g")

    def test_two_levels_and_cycles_are_refused(self):
        nodes = [_node("top", "group"), _node("mid", "group", groupId="top"), _node("leaf", "group"), _node("x", groupId="leaf")]
        with self.assertRaises(studio_canvas.CanvasOperationError):
            _apply(nodes, [{"op": "set_group", "node_ids": ["leaf"], "group_id": "mid"}])
        with self.assertRaises(studio_canvas.CanvasOperationError):
            _apply(nodes, [{"op": "group", "ids": ["top"]}])
        with self.assertRaises(studio_canvas.CanvasOperationError):
            _apply(nodes, [{"op": "set_group", "node_ids": ["top"], "group_id": "mid"}])
        with self.assertRaises(studio_canvas.CanvasOperationError):
            _apply(nodes, [{"op": "set_group", "node_ids": ["top"], "group_id": "top"}])
        with self.assertRaises(studio_canvas.CanvasOperationError):
            _apply(nodes, [{"op": "set_group", "node_ids": ["x"], "group_id": "x"}])
        with self.assertRaises(studio_canvas.CanvasOperationError):
            _apply(nodes, [{"op": "group", "ids": ["x"], "parent": "x"}])
        # The document rule says the same for a whole-canvas save.
        for bad in (
            [_node("a", "group", groupId="b"), _node("b", "group", groupId="a")],
            [_node("a", "group", groupId="a")],
            [_node("a", "group"), _node("b", "group", groupId="a"), _node("c", "group", groupId="b")],
        ):
            with self.assertRaises(ValidationError):
                CanvasPutRequest(expected_version=0, nodes=bad)
        # A leftover groupId naming nothing is tolerated, as before.
        CanvasPutRequest(expected_version=0, nodes=[_node("a", groupId="gone")])

    def test_set_group_moves_nodes_in_and_out(self):
        nodes = [_node("g", "group", x=0, y=0, width=300, height=200), _node("a", x=1000, y=1000)]
        by_id, _, _ = _apply(nodes, [{"op": "set_group", "node_ids": ["a"], "group_id": "g"}])
        self.assertEqual(by_id["a"]["payload"]["groupId"], "g")
        self.assertGreaterEqual(by_id["g"]["x"] + by_id["g"]["width"], 1200, "the frame grows to hold its new member")
        nodes = [_node("g", "group"), _node("a", groupId="g")]
        by_id, _, _ = _apply(nodes, [{"op": "set_group", "node_ids": ["a"], "group_id": None}])
        self.assertNotIn("groupId", by_id["a"]["payload"])

    def test_deleting_an_inner_group_hands_its_members_to_the_outer_one(self):
        nodes = [_node("top", "group"), _node("mid", "group", groupId="top"), _node("a", groupId="mid")]
        by_id, _, _ = _apply(nodes, [{"op": "delete_node", "id": "mid"}])
        self.assertEqual(by_id["a"]["payload"]["groupId"], "top")

    def test_collapsed_round_trips(self):
        nodes = [_node("g", "group", width=480, height=320)]
        by_id, changed, _ = _apply(nodes, [{"op": "update_node", "id": "g", "collapsed": True}])
        self.assertIs(by_id["g"]["payload"]["collapsed"], True)
        self.assertEqual(by_id["g"]["payload"]["expandedSize"], [480.0, 320.0])
        folded = CanvasPutRequest(expected_version=0, nodes=changed["nodes"])
        self.assertIs(folded.nodes[0].payload["collapsed"], True)
        shrunk = {**changed["nodes"][0], "height": 40}
        by_id, _, _ = _apply([shrunk], [{"op": "update_node", "id": "g", "collapsed": False}])
        self.assertEqual((by_id["g"]["payload"]["collapsed"], by_id["g"]["height"]), (False, 320.0))
        with self.assertRaises(studio_canvas.CanvasOperationError):
            _apply([_node("n")], [{"op": "update_node", "id": "n", "collapsed": True}])
        with self.assertRaises(studio_canvas.CanvasOperationError):
            _apply(nodes, [{"op": "update_node", "id": "g", "collapsed": "yes"}])
        for bad in ({"collapsed": 1}, {"expandedSize": [10]}, {"expandedSize": [10, -1]}, {"expandedSize": "big"}):
            with self.assertRaises(ValidationError, msg=bad):
                CanvasNode.model_validate(_node("g", "group", **bad))


class LayoutTests(unittest.TestCase):
    def test_align_on_the_selection_box(self):
        nodes = [_node("a", x=10, y=0, width=100), _node("b", x=200, y=50, width=50), _node("c", x=60, y=300, width=200)]
        for mode, expected in (
            ("left", {"a": 10, "b": 10, "c": 10}),
            ("right", {"a": 160, "b": 210, "c": 60}),
            ("hcenter", {"a": 85, "b": 110, "c": 35}),
        ):
            by_id, _, _ = _apply(json.loads(json.dumps(nodes)), [{"op": "align", "node_ids": ["a", "b", "c"], "mode": mode}])
            self.assertEqual({key: by_id[key]["x"] for key in "abc"}, expected, mode)
        by_id, _, _ = _apply(nodes, [{"op": "align", "node_ids": ["a", "b", "c"], "mode": "bottom"}])
        self.assertEqual({key: by_id[key]["y"] for key in "abc"}, {"a": 300, "b": 300, "c": 300})
        with self.assertRaises(studio_canvas.CanvasOperationError):
            _apply(nodes, [{"op": "align", "node_ids": ["a", "b"], "mode": "diagonal"}])

    def test_distribute_evens_the_gaps(self):
        nodes = [_node("a", x=0, width=100), _node("b", x=130, width=50), _node("c", x=500, width=100)]
        by_id, _, _ = _apply(nodes, [{"op": "distribute", "node_ids": ["c", "a", "b"], "axis": "horizontal"}])
        # span 600, widths 250, two gaps of 175
        self.assertEqual((by_id["a"]["x"], by_id["b"]["x"], by_id["c"]["x"]), (0, 275, 500))
        with self.assertRaises(studio_canvas.CanvasOperationError):
            _apply(nodes, [{"op": "distribute", "node_ids": ["a", "b"], "axis": "horizontal"}])

    def test_arrange_row_column_grid(self):
        nodes = [_node("a", x=50, y=10, width=100, height=80), _node("b", x=0, y=200, width=200, height=50), _node("c", x=400, y=0, width=60, height=60)]
        by_id, _, _ = _apply(json.loads(json.dumps(nodes)), [{"op": "arrange", "node_ids": ["a", "b", "c"], "layout": "row"}])
        self.assertEqual([(by_id[key]["x"], by_id[key]["y"]) for key in "bac"], [(0, 0), (240, 0), (380, 0)])
        by_id, _, _ = _apply(json.loads(json.dumps(nodes)), [{"op": "arrange", "node_ids": ["a", "b", "c"], "layout": "column", "gap": 10}])
        self.assertEqual([(by_id[key]["x"], by_id[key]["y"]) for key in "cab"], [(0, 0), (0, 70), (0, 160)])
        by_id, _, _ = _apply(nodes, [{"op": "arrange", "node_ids": ["a", "b", "c"], "layout": "grid"}])
        # Two columns of the widest cell (200), reading order c, a / b.
        self.assertEqual([(by_id[key]["x"], by_id[key]["y"]) for key in "cab"], [(0, 0), (240, 0), (0, 120)])

    def test_arrange_by_edges_puts_upstream_left(self):
        nodes = [_node("note", x=900, y=900), _node("img", "image_gen", x=0, y=500, width=300, height=320), _node("vid", "video_gen", x=-500, y=0, width=320, height=340)]
        edges = [{"id": "e1", "source": "note", "target": "img"}, {"id": "e2", "source": "img", "target": "vid"}, {"id": "e3", "source": "note", "target": "vid"}]
        by_id, _, _ = _apply(nodes, [{"op": "arrange", "node_ids": ["vid", "img", "note"], "layout": "edges"}], edges)
        self.assertEqual((by_id["note"]["x"], by_id["note"]["y"]), (-500, 0))
        self.assertEqual(by_id["img"]["x"], -500 + 200 + 120)
        self.assertEqual(by_id["vid"]["x"], -500 + 200 + 120 + 300 + 120)

    def test_a_group_moves_its_members_and_its_members_are_not_moved_twice(self):
        nodes = [
            _node("g", "group", x=1000, y=1000, width=500, height=300),
            _node("m", x=1040, y=1060, groupId="g"),
            _node("sub", "group", x=1100, y=1100, width=300, height=150, groupId="g"),
            _node("deep", x=1140, y=1160, groupId="sub"),
            _node("free", x=0, y=0),
        ]
        by_id, _, _ = _apply(nodes, [{"op": "align", "node_ids": ["g", "m", "free"], "mode": "left"}])
        self.assertEqual((by_id["g"]["x"], by_id["m"]["x"], by_id["sub"]["x"], by_id["deep"]["x"]), (0, 40, 100, 140))
        self.assertEqual(by_id["free"]["x"], 0)

    def test_moving_members_out_of_their_frame_grows_the_frame(self):
        nodes = [_node("g", "group", x=0, y=0, width=300, height=200), _node("a", x=40, y=60, groupId="g"), _node("b", x=40, y=60, groupId="g")]
        by_id, _, _ = _apply(nodes, [{"op": "arrange", "node_ids": ["a", "b"], "layout": "row"}])
        self.assertEqual(by_id["b"]["x"], 280)
        self.assertGreaterEqual(by_id["g"]["width"], 280 + 200 + 40)

    def test_bounds_helper(self):
        self.assertIsNone(canvas_layout.bounds([]))
        self.assertEqual(canvas_layout.bounds([_node("a", x=-10, y=5), _node("b", x=100, y=-20, width=10, height=10)]), {"x": -10, "y": -20, "width": 200, "height": 125})


class AgentCanvasTests(CanvasCase):
    def call(self, name, **arguments):
        with patch("app.api.studio_api.get_studio_service", return_value=self.studio):
            return catalog.call(name, {"task_id": "t-1", **arguments}, service=self.drama, user=self.user)

    def test_far_coordinates_save_over_http(self):
        saved = self.put([_node("far", x=-8e8, y=7e8, width=500_000, height=500_000)])
        self.assertEqual(saved["version"], 1)
        bad = self.client.put(f"{self.base}/canvas", json={"expected_version": 1, "nodes": [_node("a", x=2e9)], "edges": []})
        self.assertEqual(bad.status_code, 422)
        bookmark = self.client.patch(f"{self.base}/canvases/main", json={"bookmarks": [{"slot": 1, "x": 5e9, "y": -5e9, "zoom": 0.02}]})
        self.assertEqual(bookmark.status_code, 200, bookmark.text)

    def test_edit_canvas_reports_what_changed_for_the_ui(self):
        first = self.call("edit_canvas", operations=[
            {"op": "add_node", "ref": "a", "kind": "note", "text": "一"},
            {"op": "add_node", "ref": "b", "kind": "note", "text": "二"},
            {"op": "add_node", "ref": "c", "kind": "image_gen"},
        ])
        self.assertTrue(first["ok"], first)
        created = first["result"]["created"]
        action = first["result"]["ui_action"]
        self.assertEqual((action["type"], action["canvas_id"], action["version"]), ("canvas_changed", "main", 1))
        self.assertEqual(set(action["node_ids"]), set(created.values()))

        tidy = self.call("edit_canvas", operations=[{"op": "arrange", "node_ids": [created["a"], created["b"]], "layout": "column"}])
        self.assertEqual(tidy["result"]["ui_action"]["version"], 2)
        self.assertEqual(set(tidy["result"]["ui_action"]["node_ids"]), {created["b"]})

        wired = self.call("edit_canvas", operations=[{"op": "connect", "source": created["a"], "target": created["c"]}])
        self.assertEqual(set(wired["result"]["ui_action"]["node_ids"]), {created["a"], created["c"]})

    def test_get_canvas_has_bounds_and_group_membership(self):
        done = self.call("edit_canvas", operations=[
            {"op": "add_node", "ref": "a", "kind": "note", "x": -1000, "y": -500},
            {"op": "add_node", "ref": "b", "kind": "note", "x": 4000, "y": 2000},
            {"op": "group", "ref": "g", "ids": ["a"], "label": "左"},
        ])
        self.assertTrue(done["ok"], done)
        read = self.call("get_canvas")["result"]
        self.assertEqual(read["bounds"], {"x": -1040.0, "y": -560.0, "width": 5280.0, "height": 2710.0})
        rows = {row["id"]: row for row in read["nodes"]}
        self.assertEqual(rows[done["result"]["created"]["a"]]["group"], done["result"]["created"]["g"])
        self.assertIsNone(rows[done["result"]["created"]["b"]]["group"])
        self.assertIs(rows[done["result"]["created"]["g"]]["collapsed"], False)
        for op in ("set_group", "align", "distribute", "arrange"):
            self.assertIn(op, read["operations"])


if __name__ == "__main__":
    unittest.main()
