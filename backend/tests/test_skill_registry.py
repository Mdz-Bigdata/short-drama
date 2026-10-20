import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from app.core.skill_registry import SkillRegistry
from app.core.sd25_skill_bundle import load_sd25_skill_bundle
from app.core.model_gateway import ModelGateway


class SkillRegistryTests(unittest.TestCase):
    def test_sd25_pe_is_loaded_as_prompt_compiler_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            skill_dir = root / "sd25-pe"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                "---\nname: sd25-pe\ndescription: optimizer\n---\n# Body\n素材逐份负责\n",
                encoding="utf-8",
            )
            registry = SkillRegistry([root])
            skill = registry.get("sd25-pe")
            self.assertEqual(skill.name, "sd25-pe")
            self.assertIn("素材逐份负责", skill.instructions)
            self.assertEqual(skill.kind, "prompt_compiler")

    def test_registry_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = SkillRegistry([Path(tmp)])
            with self.assertRaises(ValueError):
                registry.get("../secret")

    def test_sd25_bundle_keeps_primary_complete_and_adds_five_part_guidance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = "---\nname: sd25-pe\n---\n" + ("素材逐份负责\n" * 1000)
            (root / "SKILL.md").write_text(body, encoding="utf-8")
            supplemental = root / "five-part"
            supplemental.mkdir()
            supplemental_body = "---\nname: sd-2-5-prompt\n---\n五段式结构审计\n"
            (supplemental / "SKILL.md").write_text(supplemental_body, encoding="utf-8")
            references = supplemental / "references"
            references.mkdir()
            (references / "formula.md").write_text("五段公式详情\n", encoding="utf-8")
            (references / "modes.md").write_text("延长与编辑模式详情\n", encoding="utf-8")

            loaded = load_sd25_skill_bundle(
                primary_candidates=[root / "SKILL.md"],
                supplemental_candidates=[supplemental / "SKILL.md"],
            )

            self.assertIn(body, loaded)
            self.assertIn(supplemental_body, loaded)
            self.assertIn("五段公式详情", loaded)
            self.assertIn("延长与编辑模式详情", loaded)
            self.assertIn("sd25-pe 的任务路由、参数分离与素材引用保真规则优先", loaded)
            self.assertEqual(loaded.count("素材逐份负责"), 1000)
            # First-party blockout rules ride along after the primary skill without editing it.
            self.assertIn("# 项目补充：白模实战规则", loaded)
            self.assertIn("提示词正文一个运镜词都不要写", loaded)
            self.assertLess(loaded.index(body), loaded.index("# 项目补充：白模实战规则"))
            self.assertLess(loaded.index("# 项目补充：白模实战规则"), loaded.index(supplemental_body))

    def test_model_gateway_loads_integrated_sd25_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = "---\nname: sd25-pe\n---\n素材逐份负责\n"
            (root / "SKILL.md").write_text(body, encoding="utf-8")
            gateway = ModelGateway.__new__(ModelGateway)
            gateway._sd2_opt_prompt_cache = None
            with patch.dict("os.environ", {"SD25_PE_SKILL_PATH": str(root)}):
                loaded = gateway._load_sd2_optimizer_prompt()
            self.assertIn(body, loaded)
            self.assertIn("sd-2-5-prompt", loaded)

    def test_bundled_sd25_skills_are_both_discoverable(self):
        root = Path(__file__).resolve().parents[1] / "skills"

        names = {skill.name for skill in SkillRegistry([root]).list()}

        self.assertIn("sd25-pe", names)
        self.assertIn("sd-2-5-prompt", names)


if __name__ == "__main__":
    unittest.main()
