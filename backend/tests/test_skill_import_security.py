import unittest

from app.service.drama_service import _safe_skill_name


class SkillImportSecurityTests(unittest.TestCase):
    def test_skill_name_cannot_resolve_to_root_or_parent(self):
        for unsafe in ("", ".", "..", "@@@", "///"):
            with self.subTest(unsafe=unsafe):
                with self.assertRaises(ValueError):
                    _safe_skill_name(unsafe)

    def test_skill_name_removes_path_separators(self):
        self.assertEqual(_safe_skill_name("../../my-skill"), "my-skill")


if __name__ == "__main__":
    unittest.main()
