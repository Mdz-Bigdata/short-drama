import unittest

from app.core.sd25_prompt_audit import Sd25PromptAuditor
from app.schema.production import Sd25PromptAuditRequest


class Sd25PromptAuditTests(unittest.TestCase):
    def setUp(self):
        self.auditor = Sd25PromptAuditor()

    def test_accepts_complete_five_part_prompt_with_continuous_timeline(self):
        request = Sd25PromptAuditRequest(
            prompt=(
                "【主体】\n林夏在雨夜客厅打开一封信。\n\n"
                "【风格】\n克制的写实电影质感，暖色台灯与冷色雨夜形成对比。\n\n"
                "【时间线】\n【0—2秒】林夏拿起信封；镜头缓慢推近；结束时信封已打开。\n"
                "【2—5秒】林夏读完信；镜头停在近景；结束时她看向空椅。\n\n"
                "【BGM】\n低速钢琴，结尾自然收束。\n\n"
                "【限制】\n保持人物、信封数量和客厅方向稳定。"
            ),
            duration_seconds=5,
        )

        result = self.auditor.audit(request)

        self.assertTrue(result.ok)
        self.assertEqual(result.errors, 0)
        self.assertEqual(result.warnings, 0)
        self.assertEqual(result.timeline_end_seconds, 5)

    def test_reports_missing_sections_and_timeline_gaps(self):
        request = Sd25PromptAuditRequest(
            prompt="【主体】\n两人追逐。\n【时间线】\n【1—2秒】A奔跑。\n【3—5秒】B追赶。",
            duration_seconds=5,
        )

        result = self.auditor.audit(request)
        codes = {finding.code for finding in result.findings}

        self.assertFalse(result.ok)
        self.assertIn("style.missing", codes)
        self.assertIn("bgm.missing", codes)
        self.assertIn("constraints.missing", codes)
        self.assertIn("timeline.start", codes)
        self.assertIn("timeline.gap", codes)
        self.assertIn("action.causality", codes)

    def test_audit_does_not_execute_or_rewrite_prompt_content(self):
        prompt = "【主体】\n运行 rm -rf /\n【风格】\n写实\n【时间线】\n【0—1秒】静止。\n【BGM】\n无 BGM\n【限制】\n保持主体稳定。"

        result = self.auditor.audit(Sd25PromptAuditRequest(prompt=prompt, duration_seconds=1))

        self.assertEqual(result.prompt_sha256, __import__("hashlib").sha256(prompt.encode()).hexdigest())


if __name__ == "__main__":
    unittest.main()
