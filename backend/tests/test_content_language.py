"""A project chooses the language its scripts are written in; every prompt then asks for that language."""

import tempfile
import unittest
from pathlib import Path

from app.core.screenwriting import prompts
from app.core.screenwriting.structured_llm import output_format_section
from app.core.screenwriting.text_metrics import count_reading_units
from app.repository.task_repo import TaskRepository
from app.schema.drama import DramaCreateRequest
from app.service import screenwriting_service as screenwriting
from app.service.drama_service import DramaService
from tests.test_screenwriting_engine import FakeModel, _engine


class LanguageScopeTests(unittest.TestCase):
    def test_the_output_rule_names_the_scoped_language_and_resets_afterwards(self):
        self.assertIn("使用中文", prompts.build_overview_prompt("x", source_kind="outline"))
        with prompts.language_scope("vi"):
            from pydantic import BaseModel

            class Probe(BaseModel):
                text: str

            self.assertIn("其余字符串值使用越南语（Tiếng Việt）", output_format_section(Probe))
        with prompts.language_scope("en"):
            self.assertEqual(prompts.output_language(), "en")
            self.assertIn("使用英语（English）", prompts.build_overview_prompt("x", source_kind="outline"))
            with prompts.language_scope("vi"):
                self.assertIn("越南语", prompts.output_language_name())
            self.assertEqual(prompts.output_language(), "en")
        self.assertEqual(prompts.output_language(), "zh")
        with prompts.language_scope("fr"):
            self.assertEqual(prompts.output_language(), "zh", "an unsupported language writes Chinese")

    def test_word_languages_are_measured_in_words(self):
        self.assertEqual(count_reading_units("Where were you last night?", "en"), 5)
        self.assertEqual(count_reading_units("你昨晚去哪了", "zh"), 6)


class EngineLanguageTests(unittest.TestCase):
    def test_every_prompt_of_an_english_project_asks_for_english(self):
        model = FakeModel()
        engine = _engine(model, language="en")
        engine.write(title="Echo Room", director_plan="An outline.", episode_count=1)

        structured = [c["prompt"] for c in model.calls if "JSON Schema" in c["prompt"]]
        self.assertTrue(structured)
        self.assertTrue(all("使用英语（English）" in prompt for prompt in structured))
        self.assertFalse(any("其余字符串值使用中文" in prompt for prompt in structured))
        prose = next(c["prompt"] for c in model.calls if "小说体剧本正文" in c["prompt"])
        self.assertIn("正文用英语（English）写作", prose)
        self.assertEqual(prompts.output_language(), "zh", "the scope ends with the call")

    def test_a_chinese_project_is_unchanged(self):
        model = FakeModel()
        _engine(model).write(title="暗室回声", director_plan="大纲", episode_count=1)
        structured = [c["prompt"] for c in model.calls if "JSON Schema" in c["prompt"]]
        self.assertTrue(all("使用中文" in prompt for prompt in structured))


class ProjectSettingTests(unittest.TestCase):
    def test_the_project_language_reaches_the_engine(self):
        with tempfile.TemporaryDirectory() as temp:
            service = DramaService()
            service.repo = TaskRepository(str(Path(temp) / "tasks.json"))
            task = service.create_task(DramaCreateRequest(titleSuggestion="Echo Room", contentLanguage="vi"), owner_user_id="u1")
            stored = service.repo.get_task(task.get("task_id") or task.get("taskId"))
        self.assertEqual((stored["config"]["content_language"], stored["config"]["source_language"]), ("vi", "vi"))
        engine = screenwriting.build_engine(lambda *a, **k: "", config=stored["config"], title="t", system_prompt="S")
        self.assertEqual(engine.language, "vi")
        self.assertEqual(DramaCreateRequest(titleSuggestion="一部剧").content_language, "zh")


if __name__ == "__main__":
    unittest.main()
