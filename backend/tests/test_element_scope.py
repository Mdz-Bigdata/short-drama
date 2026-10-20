import unittest

from app.core.element_scope import (
    element_in_task,
    element_name_keys,
    element_task_ids,
    link_task,
    normalized_asset_name,
)


class ElementScopeTests(unittest.TestCase):
    def test_names_match_across_spacing_punctuation_and_case(self):
        self.assertEqual(normalized_asset_name("《长安 城门》"), normalized_asset_name("长安城门"))
        self.assertEqual(normalized_asset_name(" Iron-Door "), normalized_asset_name("irondoor"))
        self.assertEqual(normalized_asset_name(None), "")
        self.assertEqual(
            element_name_keys("含元殿", {"aliases": "含元殿偏殿、大殿"}),
            {"含元殿", "含元殿偏殿", "大殿"},
        )

    def test_origin_task_stays_first_and_links_never_duplicate(self):
        metadata = link_task({"task_id": "task-a", "source": "screenplay-extraction"}, "task-b")
        self.assertEqual(metadata["task_id"], "task-a")
        self.assertEqual(metadata["task_ids"], ["task-a", "task-b"])
        self.assertEqual(link_task(metadata, "task-b")["task_ids"], ["task-a", "task-b"])
        self.assertEqual(element_task_ids(metadata), ("task-a", "task-b"))
        self.assertTrue(element_in_task(metadata, "task-b"))
        self.assertFalse(element_in_task(metadata, "task-c"))
        self.assertFalse(element_in_task(metadata, ""))

    def test_linking_an_orphan_element_adopts_the_task_as_origin(self):
        metadata = link_task({}, "task-new")
        self.assertEqual(metadata, {"task_id": "task-new", "task_ids": ["task-new"]})
        self.assertEqual(link_task("not-a-dict", ""), {})
        self.assertEqual(element_task_ids({"task_ids": ["x", "", None, "x"]}), ("x",))


if __name__ == "__main__":
    unittest.main()
