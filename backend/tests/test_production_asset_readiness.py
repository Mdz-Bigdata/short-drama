import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.core.production_asset_readiness import (
    READINESS_KEY,
    element_summary,
    evaluate_asset_readiness,
    readiness_reasons,
)
from app.core.storyboard_scene_context import merge_video_references
from app.service.drama_service import DramaService, StagePrerequisiteError


def _views(prefix: str) -> list[dict[str, str]]:
    return [
        {"view": view, "image_url": f"/media/{prefix}/{view}.png"}
        for view in ("front", "front_three_quarter", "profile", "rear_three_quarter", "back")
    ]


def _task(*, ready_cast: bool = True) -> dict:
    return {
        "task_id": "task-gate",
        "owner_user_id": "owner-one",
        "config": {"title_suggestion": "朕的江山"},
        "assets": {
            "3": "角色设定",
            "3_sheets": {"沈砚": "/media/sheets/shen.png"},
            "3_characters": [{
                "name": "沈砚", "role": "主角", "desc": "长发束起",
                "sheet": "/media/sheets/shen.png", "views": _views("shen"),
                "five_view_quality": {"passed": ready_cast, "unique_view_hashes": 5, "issues": []},
            }],
            "2_breakdown": {"production_assets": {
                "scenes": [{"name": "长安城门", "description": "夜，外景"}, {"name": "含元殿", "description": "大殿"}],
                "props": [{"name": "青铜剑", "description": "剑"}],
                "costumes": [],
                "effects": [{"name": "火药爆炸", "description": "火光"}],
            }},
        },
    }


def _summary(kind: str, name: str, has_image: bool, task_ids=("task-gate",)) -> dict:
    return {"id": f"{kind}-{name}", "kind": kind, "name": name, "has_image": has_image,
            "metadata": {"task_id": task_ids[0], "task_ids": list(task_ids)}}


class AssetReadinessTests(unittest.TestCase):
    def test_every_named_asset_needs_a_reference_image_before_the_project_is_complete(self):
        summaries = [
            _summary("scene", "长安城门", True),
            _summary("scene", "含元殿", False),
            _summary("prop", "青铜 剑", True),
            _summary("effect", "火药爆炸", True, task_ids=("older", "task-gate")),
        ]
        readiness = evaluate_asset_readiness(_task(), summaries)

        self.assertFalse(readiness["complete"])
        self.assertEqual(readiness["kinds"]["actor"], {
            "label": "数字演员", "total": 1, "ready": 1, "missing": [], "enforced": True,
        })
        self.assertEqual(readiness["kinds"]["scene"]["missing"], ["含元殿"])
        self.assertEqual((readiness["kinds"]["scene"]["total"], readiness["kinds"]["scene"]["ready"]), (2, 1))
        self.assertEqual(readiness["kinds"]["prop"]["missing"], [])
        self.assertEqual(readiness["kinds"]["costume"]["total"], 0)
        self.assertEqual(readiness["kinds"]["effect"]["missing"], [])
        self.assertEqual(readiness_reasons(readiness), ["3.拍摄场地缺少参考图（1项）：含元殿"])

        summaries[1]["has_image"] = True
        self.assertTrue(evaluate_asset_readiness(_task(), summaries)["complete"])
        self.assertEqual(readiness_reasons(evaluate_asset_readiness(_task(), summaries)), [])

    def test_actor_contract_and_library_errors_block_completion(self):
        full = [_summary("scene", "长安城门", True), _summary("scene", "含元殿", True),
                _summary("prop", "青铜剑", True), _summary("effect", "火药爆炸", True)]
        cast_not_ready = evaluate_asset_readiness(_task(ready_cast=False), full)
        # The persisted dashboard contract, when present, is what the gate trusts.
        persisted = _task()
        persisted["assets"]["3_character_dashboard"] = {
            "state": "INCOMPLETE",
            "characters": [{"name": "沈砚", "assetState": "READY"}, {"name": "贺兰霆", "assetState": "MISSING"}],
        }
        self.assertEqual(evaluate_asset_readiness(persisted, full)["kinds"]["actor"], {
            "label": "数字演员", "total": 2, "ready": 1, "missing": ["贺兰霆"], "enforced": True,
        })
        self.assertFalse(cast_not_ready["complete"])
        self.assertEqual(cast_not_ready["kinds"]["actor"]["missing"], ["沈砚"])
        self.assertEqual(readiness_reasons(cast_not_ready), ["3.数字演员缺少参考图（1项）：沈砚"])

        broken = evaluate_asset_readiness(_task(), None, library_error="ConnectionRefusedError")
        self.assertFalse(broken["complete"])
        self.assertFalse(broken["library_scoped"])
        self.assertEqual(readiness_reasons(broken)[0], "3.资产库读取失败：ConnectionRefusedError")

        # A legacy task without a library scope is only held to the actor contract.
        legacy = evaluate_asset_readiness(_task(), None)
        self.assertTrue(legacy["complete"])
        self.assertFalse(legacy["kinds"]["scene"]["enforced"])

    def test_element_summary_enforces_owner_and_project_scope_without_reading_files(self):
        item = SimpleNamespace(
            id="e1", owner_id="owner-one", kind="prop", name="青铜剑",
            metadata_json={"task_id": "other", "task_ids": ["other", "task-gate"]},
            files=[SimpleNamespace(mime_type="model/gltf-binary"), SimpleNamespace(mime_type="image/png")],
        )
        summary = element_summary(item, "owner-one", "task-gate")
        self.assertTrue(summary["has_image"])
        self.assertIsNone(element_summary(item, "owner-two", "task-gate"))
        self.assertIsNone(element_summary(item, "owner-one", "task-unrelated"))

    def test_stage_gates_read_the_snapshot_and_recheck_the_library_before_stage_four(self):
        task = _task()
        task["assets"].update({"3_character_dashboard": {"state": "READY"}})
        task["assets"][READINESS_KEY] = evaluate_asset_readiness(task, [_summary("scene", "长安城门", True)])
        missing = DramaService._missing_stage_outputs(task, 3)
        self.assertTrue(any(reason.startswith("3.拍摄场地缺少参考图") for reason in missing))
        self.assertTrue(any(reason.startswith("3.拍摄道具缺少参考图") for reason in missing))

        task["assets"][READINESS_KEY] = evaluate_asset_readiness(task, None)
        self.assertEqual(DramaService._missing_stage_outputs(task, 3), [])
        service = DramaService.__new__(DramaService)
        # Earlier-stage outputs are covered elsewhere; isolate the live library recheck.
        with patch.object(DramaService, "_missing_stage_outputs", return_value=[]):
            with patch("app.service.drama_service.evaluate_project_assets", return_value=evaluate_asset_readiness(
                task, [_summary("scene", "长安城门", True)],
            )):
                with self.assertRaisesRegex(StagePrerequisiteError, "含元殿"):
                    service._assert_stage_prerequisites(task, 4)
            self.assertFalse(task["assets"][READINESS_KEY]["complete"])
            with patch("app.service.drama_service.evaluate_project_assets", return_value=evaluate_asset_readiness(
                task, [_summary("scene", "长安城门", True), _summary("scene", "含元殿", True),
                       _summary("prop", "青铜剑", True), _summary("effect", "火药爆炸", True)],
            )):
                service._assert_stage_prerequisites(task, 4)
            self.assertTrue(task["assets"][READINESS_KEY]["complete"])

    def test_video_references_keep_sheets_first_and_label_every_asset(self):
        images, notes = merge_video_references(
            [("沈砚", "https://cdn/shen-sheet.png"), ("无图角色", "")],
            [
                {"kind": "actor", "name": "沈砚", "image_url": "data:image/png;base64,AAA"},
                {"kind": "scene", "name": "长安城门", "image_url": "data:image/png;base64,BBB"},
                {"kind": "prop", "name": "青铜剑", "image_url": "https://cdn/shen-sheet.png"},
                {"kind": "effect", "name": "火药爆炸", "image_url": ""},
            ],
        )
        self.assertEqual(images, ["https://cdn/shen-sheet.png", "data:image/png;base64,AAA", "data:image/png;base64,BBB"])
        self.assertIn("参考图1仅锁定数字演员设定集「沈砚」", notes)
        self.assertIn("参考图3仅锁定拍摄场地「长安城门」", notes)
        self.assertNotIn("青铜剑", notes)
        capped, _ = merge_video_references([], [
            {"kind": "prop", "name": f"p{i}", "image_url": f"https://cdn/{i}.png"} for i in range(12)
        ])
        self.assertEqual(len(capped), 9)


if __name__ == "__main__":
    unittest.main()
