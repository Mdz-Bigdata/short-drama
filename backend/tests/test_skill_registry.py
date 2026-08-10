import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from app.core.skill_registry import SkillRegistry
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

    def test_model_gateway_loads_named_sd25_skill_without_truncation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = "---\nname: sd25-pe\n---\n" + ("素材逐份负责\n" * 1000)
            (root / "SKILL.md").write_text(body, encoding="utf-8")
            gateway = ModelGateway.__new__(ModelGateway)
            gateway._sd2_opt_prompt_cache = None
            with patch.dict("os.environ", {"SD25_PE_SKILL_PATH": str(root)}):
                loaded = gateway._load_sd2_optimizer_prompt()
            self.assertEqual(loaded, body)


if __name__ == "__main__":
    unittest.main()
