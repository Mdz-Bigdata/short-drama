import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import drama_api
from app.api.auth_api import get_current_user
from app.core.character_dashboard import compile_character_dashboard
from app.core.image_quality import FiveViewQualityReport
from app.repository.task_repo import TaskRepository
from app.schema.drama import DramaCreateRequest
from app.schema.production import FIVE_VIEW_ORDER
from app.service.drama_service import DramaService, parse_all_characters, parse_characters
from main import app


def _views(name: str) -> list[dict]:
    # Deliberately shuffled: the compiler must return the production-contract order.
    return [
        {"view": "back", "image_url": f"https://cdn.example/{name}/back.png"},
        {"view": "profile", "image_url": f"https://cdn.example/{name}/profile.png"},
        {"view": "front", "image_url": f"https://cdn.example/{name}/front.png"},
        {"view": "rear_three_quarter", "image_url": f"https://cdn.example/{name}/rear-3q.png"},
        {"view": "front_three_quarter", "image_url": f"/media/{name}/front-3q.png"},
    ]


def _task() -> dict:
    return {
        "task_id": "character-task-1",
        "owner_user_id": "character-user",
        "status": "idle",
        "config": {"title_suggestion": "渡口"},
        "assets": {
            "3": "## 主角：沈知微\n十九岁，学生，深蓝校服。",
            "3_sheets": {"沈知微": "https://cdn.example/shen/sheet.png"},
            "3_characters": [{
                "name": "沈知微",
                "role": "主角",
                "desc": "十九岁，黑色双辫，深蓝校服。",
                "sheet": "javascript:alert(1)",
                "views": _views("shen"),
                "five_view_quality": {
                    "passed": True,
                    "palette_similarity": 0.91,
                    "unique_view_hashes": 5,
                    "entropy": [6.1, 6.2, 6.3, 6.4, 6.5],
                    "issues": [],
                },
            }],
            "3_dna": {
                "project": {
                    "genre": "民国悬疑",
                    "platform": "竖屏短剧",
                    "delivery_spec": "1080×1920, 9:16, 30fps",
                    "constraints": "五视图服装和发型必须一致。",
                },
                "assumptions": ["角色均为虚构人物。"],
                "risks": [{"item": "授权素材", "status": "PASS", "note": "已确认。"}],
                "characters": [{
                    "character_id": "unstable-upstream-id",
                    "name": "沈知微",
                    "identity": "学生/调查者",
                    "voice_id": "VC_SHEN",
                    "colors": [{"name": "深蓝", "hex": "#10243F"}],
                    "states": [{
                        "state_id": "student",
                        "title": "学生状态",
                        "dna": "克制、警觉的学生造型。",
                        "hair": "黑色双辫",
                        "body": "清瘦",
                        "clothing": "深蓝校服",
                        "accessories": "旧皮箱",
                        "style": "1930年代写实",
                        "anchors": [
                            {"view": "背面", "detail": "双辫与衣领"},
                            {"view": "正面", "detail": "圆领与胸前纽扣"},
                            {"view": "标准侧面", "detail": "鼻梁和发辫轮廓"},
                            {"view": "正面四分之三", "detail": "脸型与皮箱带"},
                            {"view": "背面四分之三", "detail": "肩线与发辫"},
                        ],
                    }],
                }],
            },
        },
    }


class CharacterCardParserTests(unittest.TestCase):
    def test_real_markdown_ignores_indexes_sections_and_bare_role_labels(self):
        markdown = """
# 角色设计方案

## 第一章：角色 UID 总表

| 角色 UID | 姓名 | 类型 |
| --- | --- | --- |
| char_001 | 沈知微 | 主角 |
| char_002 | 陆行远 | 反派 |

## 角色总表
### 主角
**角色身份**：主角
### 反派
**角色身份**：反派

## 角色卡
### 主角：沈知微
十九岁，深蓝校服。
#### 面部 DNA
杏眼，眉形平直。

### 反派：陆行远
二十八岁，黑色风衣。
"""
        parsed = parse_all_characters(markdown)

        self.assertEqual(list(parsed), ["沈知微", "陆行远"])
        self.assertIn("面部 DNA", parsed["沈知微"])
        for false_name in ("角色", "总表", "角色总表", "主角", "反派"):
            self.assertNotIn(false_name, parsed)

        primary = parse_characters(markdown, {"主角": "fallback-primary", "反派": "fallback-villain"})
        self.assertTrue(primary["主角"].startswith("**沈知微**"))
        self.assertTrue(primary["反派"].startswith("**陆行远**"))

    def test_strict_header_rejects_role_words_as_names(self):
        markdown = """
## 章节标题
## 角色 UID 总表
## 总表
### 主角
### 反派
### 主角：反派
### 角色：主角
"""
        self.assertEqual(parse_all_characters(markdown), {})


class CharacterDashboardCompilerTests(unittest.TestCase):
    def test_merges_sources_and_returns_the_exact_canonical_five_view_contract(self):
        dashboard = compile_character_dashboard(_task())

        self.assertEqual(dashboard.schema_version, "character-dashboard.v1")
        self.assertEqual(tuple(dashboard.view_contract.order), FIVE_VIEW_ORDER)
        self.assertEqual([item.angle_degrees for item in dashboard.view_contract.views], [0, 45, 90, 135, 180])
        self.assertEqual(dashboard.view_contract.views[2].label_zh, "标准侧面")
        self.assertEqual([item.key for item in dashboard.characters[0].views], list(FIVE_VIEW_ORDER))
        self.assertTrue(all(item.available for item in dashboard.characters[0].views))
        self.assertEqual(dashboard.characters[0].asset_state, "READY")
        self.assertEqual(dashboard.characters[0].sheet_url, "https://cdn.example/shen/sheet.png")
        self.assertEqual(dashboard.characters[0].identity, "学生/调查者")
        self.assertEqual(dashboard.characters[0].states[0].anchors[2].detail, "鼻梁和发辫轮廓")
        self.assertEqual(dashboard.stats.available_view_count, 5)
        self.assertEqual(dashboard.state, "READY")

    def test_character_id_and_source_hash_are_stable_and_not_array_index_based(self):
        first = compile_character_dashboard(_task())
        reordered = copy.deepcopy(_task())
        reordered["assets"] = dict(reversed(list(reordered["assets"].items())))
        reordered["assets"]["3_dna"] = dict(reversed(list(reordered["assets"]["3_dna"].items())))
        second = compile_character_dashboard(reordered)

        self.assertEqual(first.source_hash, second.source_hash)
        self.assertEqual(first.characters[0].character_id, second.characters[0].character_id)
        self.assertRegex(first.characters[0].character_id, r"^character-[a-f0-9]{16}$")
        self.assertNotEqual(first.characters[0].character_id, "unstable-upstream-id")

        changed = copy.deepcopy(_task())
        changed["assets"]["3_characters"][0]["desc"] = "源资产已经改变"
        self.assertNotEqual(first.source_hash, compile_character_dashboard(changed).source_hash)

    def test_sheet_only_legacy_task_keeps_five_empty_slots_for_review(self):
        dashboard = compile_character_dashboard({
            "task_id": "legacy",
            "config": {"title_suggestion": "旧任务"},
            "assets": {"3_sheets": {"老周": "/media/legacy/laozhou-sheet.png"}},
        })

        self.assertEqual(len(dashboard.characters), 1)
        self.assertEqual(dashboard.characters[0].name, "老周")
        self.assertEqual(dashboard.characters[0].asset_state, "NEEDS_REVIEW")
        self.assertEqual([view.key for view in dashboard.characters[0].views], list(FIVE_VIEW_ORDER))
        self.assertFalse(any(view.available for view in dashboard.characters[0].views))
        self.assertEqual(dashboard.stats.expected_view_count, 5)
        self.assertEqual(dashboard.state, "INCOMPLETE")

    def test_raw_text_only_task_can_recover_a_character_without_inventing_media(self):
        dashboard = compile_character_dashboard({
            "task_id": "raw-only",
            "config": {},
            "assets": {"3": "## 主角：顾言\n二十八岁，灰色西装，黑色短发。"},
        })

        self.assertEqual([character.name for character in dashboard.characters], ["顾言"])
        self.assertEqual(dashboard.characters[0].asset_state, "MISSING")
        self.assertIn("灰色西装", dashboard.characters[0].description)

    def test_unresolved_stage_three_source_is_incomplete_instead_of_waiting(self):
        dashboard = compile_character_dashboard({
            "task_id": "unresolved",
            "config": {},
            "assets": {"3_dna": {"project": {"genre": "悬疑"}, "characters": []}},
        })

        self.assertEqual(dashboard.characters, [])
        self.assertEqual(dashboard.state, "INCOMPLETE")

    def test_malformed_and_unsafe_fields_are_bounded_without_breaking_the_contract(self):
        task = {
            "task_id": "malformed",
            "config": {"title_suggestion": {"not": "text"}},
            "assets": {
                "3": {"not": "text"},
                "3_sheets": {"林夏": "file:///etc/passwd", "": "https://cdn.example/no-name.png"},
                "3_characters": [
                    "not-an-object",
                    {
                        "name": "林夏",
                        "views": [
                            {"view": "front", "image_url": "javascript:alert(1)"},
                            {"view": "profile", "image_url": "https://user:secret@cdn.example/private.png"},
                            {"view": "back", "image_url": "/etc/passwd"},
                        ],
                        "five_view_quality": {
                            "passed": "true",
                            "palette_similarity": "NaN",
                            "unique_view_hashes": 999,
                            "entropy": [float("inf"), "bad"],
                            "issues": [{"code": ["bad"], "message": {"bad": True}, "view_index": 99}],
                        },
                    },
                    {
                        "name": "周教授",
                        "views": _views("zhou"),
                        "five_view_quality": {"passed": False, "issues": [{"code": "palette_drift", "message": "服装漂移"}]},
                    },
                ],
                "3_dna": {
                    "assumptions": [None, {"bad": True}, "保留这一条"],
                    "risks": [{"item": "未知状态", "status": "HACKED"}],
                    "characters": [{"name": "林夏", "colors": [{"name": "危险", "hex": "red"}], "states": "bad"}],
                },
            },
        }

        dashboard = compile_character_dashboard(task)

        self.assertEqual(dashboard.title, "未命名短剧")
        self.assertEqual([character.name for character in dashboard.characters], ["林夏", "周教授"])
        self.assertEqual(dashboard.characters[0].asset_state, "MISSING")
        self.assertIsNone(dashboard.characters[0].sheet_url)
        self.assertFalse(any(view.available for view in dashboard.characters[0].views))
        self.assertIsNone(dashboard.characters[0].quality.passed)
        self.assertEqual(dashboard.characters[1].asset_state, "FAILED")
        self.assertEqual(dashboard.assumptions, ["保留这一条"])
        self.assertEqual(dashboard.risks[0].status, "PENDING")
        serialized = json.dumps(dashboard.model_dump(mode="json", by_alias=True), ensure_ascii=False)
        self.assertNotIn("javascript:", serialized)
        self.assertNotIn("file://", serialized)
        self.assertNotIn("user:secret", serialized)


class CharacterDashboardApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.repo = TaskRepository(str(Path(self.temp.name) / "tasks.json"))
        self.repo.save_task("character-task-1", _task())
        self.service = DramaService()
        self.service.repo = self.repo
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": "character-user",
            "role": "user",
        }

    def tearDown(self):
        app.dependency_overrides.pop(get_current_user, None)
        self.temp.cleanup()

    def test_dashboard_and_export_share_the_versioned_contract_and_export_is_private(self):
        with patch.object(drama_api, "service", self.service):
            client = TestClient(app)
            response = client.get("/api/drama/character-task-1/character-dashboard")
            exported = client.get("/api/drama/character-task-1/character-dashboard/export")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["schemaVersion"], "character-dashboard.v1")
        self.assertEqual(response.json()["viewContract"]["order"], list(FIVE_VIEW_ORDER))
        self.assertEqual(exported.status_code, 200, exported.text)
        self.assertIn("attachment", exported.headers["content-disposition"])
        self.assertEqual(exported.headers["cache-control"], "private, no-store")
        self.assertEqual(exported.headers["x-content-type-options"], "nosniff")
        self.assertEqual(exported.json()["sourceHash"], response.json()["sourceHash"])

    def test_missing_task_returns_not_found_for_dashboard_and_export(self):
        with patch.object(drama_api, "service", self.service):
            client = TestClient(app)
            response = client.get("/api/drama/missing/character-dashboard")
            exported = client.get("/api/drama/missing/character-dashboard/export")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(exported.status_code, 404)


class CharacterDashboardStagePersistenceTests(unittest.TestCase):
    def test_stage_three_persists_dashboard_without_replacing_legacy_sheets(self):
        with tempfile.TemporaryDirectory() as temp:
            service = DramaService()
            service.repo = TaskRepository(str(Path(temp) / "tasks.json"))
            created = service.create_task(DramaCreateRequest(
                title_suggestion="渡口",
                llm_model="test-llm",
                image_model="test-image",
            ))
            task_id = created["task_id"]
            task = service.repo.get_task(task_id)
            task["assets"]["1"] = "核心角色：沈知微\n对手角色：陆行远"
            task["assets"]["2"] = "沈知微：你终于来了。"
            service.repo.save_task(task_id, task)

            quality = FiveViewQualityReport(
                passed=True,
                entropy=[6.0] * 5,
                palette_similarity=0.9,
                unique_view_hashes=5,
                issues=[],
            )
            view_paths = [
                Path(temp) / f"{index}_{view}.png"
                for index, view in enumerate(FIVE_VIEW_ORDER, start=1)
            ]
            llm_results = [
                "## 主角：沈知微\n十九岁，深蓝校服。\n## 反派：陆行远\n二十八岁，黑色风衣。",
                '{"project":{"genre":"民国悬疑"},"characters":[]}',
            ]

            with (
                patch.object(service, "read_md_file", return_value="guide"),
                patch.object(service.gateway, "call_llm", side_effect=llm_results),
                patch.object(service.gateway, "resolve_authorized_face", return_value=None),
                patch.object(service.gateway, "generate_character_sheet", side_effect=lambda model, name, *args, **kwargs: f"https://cdn.example/{name}/sheet.png"),
                patch("app.service.drama_service.split_five_view_sheet", return_value=view_paths),
                patch("app.service.drama_service.validate_five_view_images", return_value=quality),
                patch.object(service, "run_real_consistency_check", return_value="PASS"),
            ):
                result = service._execute_stage_blocking(task_id, 3)

            self.assertIn("3_character_dashboard", result["assets"])
            self.assertEqual(result["assets"]["3_character_dashboard"]["schemaVersion"], "character-dashboard.v1")
            self.assertEqual(set(result["assets"]["3_sheets"]), {"沈知微", "陆行远"})
            self.assertTrue(all(isinstance(url, str) for url in result["assets"]["3_sheets"].values()))
            persisted = service.repo.get_task(task_id)
            self.assertEqual(
                persisted["assets"]["3_character_dashboard"]["sourceHash"],
                result["assets"]["3_character_dashboard"]["sourceHash"],
            )

    def test_stage_three_prefers_structured_dna_names_over_markdown_sections(self):
        with tempfile.TemporaryDirectory() as temp:
            service = DramaService()
            service.repo = TaskRepository(str(Path(temp) / "tasks.json"))
            created = service.create_task(DramaCreateRequest(
                title_suggestion="渡口",
                llm_model="test-llm",
                image_model="test-image",
            ))
            task_id = created["task_id"]
            task = service.repo.get_task(task_id)
            task["assets"]["1"] = "核心角色：沈知微\n对手角色：陆行远"
            service.repo.save_task(task_id, task)

            raw = """
## 角色 UID 总表
### 主角
### 反派
### 主角：文本假名
这个名字不应覆盖结构化 DNA。
"""
            dna = {
                "project": {"genre": "民国悬疑"},
                "characters": [
                    {"name": "沈知微", "role": "主角", "identity": "学生", "states": [{"dna": "深蓝校服"}]},
                    {"name": "陆行远", "role": "反派", "identity": "商人", "states": [{"dna": "黑色风衣"}]},
                ],
            }
            quality = FiveViewQualityReport(
                passed=True,
                entropy=[6.0] * 5,
                palette_similarity=0.9,
                unique_view_hashes=5,
                issues=[],
            )
            view_paths = [Path(temp) / f"{view}.png" for view in FIVE_VIEW_ORDER]
            generated_names = []

            def generate_sheet(model, name, *args, **kwargs):
                generated_names.append(name)
                return f"https://cdn.example/{name}/sheet.png"

            with (
                patch.object(service, "read_md_file", return_value="guide"),
                patch.object(service.gateway, "call_llm", return_value=raw),
                patch.object(service, "_extract_character_dna_breakdown", return_value=dna),
                patch.object(service.gateway, "resolve_authorized_face", return_value=None),
                patch.object(service.gateway, "generate_character_sheet", side_effect=generate_sheet),
                patch("app.service.drama_service.split_five_view_sheet", return_value=view_paths),
                patch("app.service.drama_service.validate_five_view_images", return_value=quality),
                patch.object(service, "run_real_consistency_check", return_value="PASS"),
            ):
                result = service._execute_stage_blocking(task_id, 3)

            self.assertEqual(generated_names, ["沈知微", "陆行远"])
            self.assertEqual([item["name"] for item in result["assets"]["3_characters"]], generated_names)
            self.assertNotIn("文本假名", result["assets"]["3_sheets"])

    def test_stage_three_persists_completed_and_failed_characters_before_raising(self):
        for failure_mode in ("generation", "quality"):
            with self.subTest(failure_mode=failure_mode), tempfile.TemporaryDirectory() as temp:
                service = DramaService()
                service.repo = TaskRepository(str(Path(temp) / "tasks.json"))
                created = service.create_task(DramaCreateRequest(
                    title_suggestion="渡口",
                    llm_model="test-llm",
                    image_model="test-image",
                ))
                task_id = created["task_id"]
                task = service.repo.get_task(task_id)
                task["assets"]["1"] = "核心角色：沈知微\n对手角色：陆行远"
                service.repo.save_task(task_id, task)

                dna = {
                    "characters": [
                        {"name": "沈知微", "role": "主角", "identity": "学生"},
                        {"name": "陆行远", "role": "反派", "identity": "商人"},
                    ],
                }
                passed_quality = FiveViewQualityReport(
                    passed=True,
                    entropy=[6.0] * 5,
                    palette_similarity=0.9,
                    unique_view_hashes=5,
                    issues=[],
                )
                failed_quality = FiveViewQualityReport(
                    passed=False,
                    entropy=[6.0] * 5,
                    palette_similarity=0.5,
                    unique_view_hashes=5,
                    issues=[{"code": "palette_drift", "message": "服装调色漂移。"}],
                )
                view_paths = [Path(temp) / f"{view}.png" for view in FIVE_VIEW_ORDER]

                def generate_sheet(model, name, *args, **kwargs):
                    if failure_mode == "generation" and name == "陆行远":
                        raise RuntimeError("图生服务失败")
                    return f"https://cdn.example/{name}/sheet.png"

                quality_results = [passed_quality]
                if failure_mode == "quality":
                    quality_results.append(failed_quality)

                with (
                    patch.object(service, "read_md_file", return_value="guide"),
                    patch.object(service.gateway, "call_llm", return_value="## 主角：文本假名"),
                    patch.object(service, "_extract_character_dna_breakdown", return_value=dna),
                    patch.object(service.gateway, "resolve_authorized_face", return_value=None),
                    patch.object(service.gateway, "generate_character_sheet", side_effect=generate_sheet),
                    patch("app.service.drama_service.split_five_view_sheet", return_value=view_paths),
                    patch("app.service.drama_service.validate_five_view_images", side_effect=quality_results),
                    patch.object(service, "run_real_consistency_check", return_value="PASS"),
                ):
                    with self.assertRaises(RuntimeError):
                        asyncio.run(service.execute_stage(task_id, 3))

                persisted = service.repo.get_task(task_id)
                self.assertEqual(persisted["status"], "failed")
                self.assertEqual(
                    [item["name"] for item in persisted["assets"]["3_characters"]],
                    ["沈知微", "陆行远"],
                )
                first, second = persisted["assets"]["3_characters"]
                self.assertTrue(first["five_view_quality"]["passed"])
                self.assertFalse(second["five_view_quality"]["passed"])
                self.assertTrue(second["five_view_quality"]["issues"])
                dashboard = persisted["assets"]["3_character_dashboard"]
                self.assertEqual(dashboard["stats"]["readyCount"], 1)
                self.assertEqual(dashboard["stats"]["failedCount"], 1)
                self.assertEqual(dashboard["state"], "INCOMPLETE")
                self.assertEqual(
                    [item["assetState"] for item in dashboard["characters"]],
                    ["READY", "FAILED"],
                )


if __name__ == "__main__":
    unittest.main()
