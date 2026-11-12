"""编剧阶段先出创作看板和人物关系，再据此规划分集账本、撰写完整剧本。"""

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.core import script_detail
from app.core.screenwriting import prompts
from app.repository.task_repo import TaskRepository
from app.service.drama_service import DramaService

from tests.test_script_outline_first import TASK, _GatedGateway, _wait_for
from tests.test_screenwriting_pipeline import _MINIATURE_ENVIRONMENT, _service, _task

RELATION = "周教授 ↔ 林夏：亦师亦友"


class _RecordingGateway(_GatedGateway):
    """Records every structured prompt, and what the stored task looked like when the ledger was first asked for."""

    def __init__(self, repo: TaskRepository):
        super().__init__()
        self.repo = repo
        self.prompts: list[str] = []
        self.at_ledger: dict | None = None
        self.board_at_ledger = None
        self.service: DramaService | None = None

    def call_llm(self, model, system_prompt, user_prompt, *args, **kwargs):
        self.prompts.append(user_prompt)
        if "分集规划师" in user_prompt and self.at_ledger is None:
            self.at_ledger = self.repo.get_task(TASK)
            self.board_at_ledger = self.service.get_writer_dashboard(TASK) if self.service else None
        return super().call_llm(model, system_prompt, user_prompt, *args, **kwargs)


class BoardFirstStageTests(unittest.TestCase):
    def setUp(self):
        _MINIATURE_ENVIRONMENT.start()
        self.addCleanup(_MINIATURE_ENVIRONMENT.stop)
        environment = patch.dict("os.environ", {"SCRIPT_OUTLINE_FIRST": "1", "QC_IN_BACKGROUND": "0"})
        environment.start()
        self.addCleanup(environment.stop)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.repo = TaskRepository(str(Path(temp.name) / "tasks.json"))
        self.repo.save_task(TASK, _task(TASK))
        qc = patch.object(DramaService, "run_real_consistency_check", return_value="QC-OK")
        qc.start()
        self.addCleanup(qc.stop)

    def test_the_board_and_the_relationships_show_before_the_ledger_is_planned(self):
        gateway = _RecordingGateway(self.repo)
        service = _service(gateway, self.repo)
        gateway.service = service
        asyncio.run(service.execute_stage(TASK, 2))

        # 1) 创作看板与人物关系先出：账本还没开始问，任务上已经有角色和关系，看板接口也能拿到。
        self.assertIsNotNone(gateway.at_ledger, "the ledger was planned")
        early = gateway.at_ledger["assets"]["2_breakdown"]
        self.assertEqual({role["name"] for role in early["roles"]}, {"林夏", "周教授"})
        self.assertEqual([edge["relation"] for edge in early["relationships"]], ["亦师亦友"])
        self.assertEqual(gateway.at_ledger["assets"].get("2", ""), "", "no screenplay text is shown that early")
        board = gateway.board_at_ledger
        self.assertEqual({role.name for role in board.roles}, {"林夏", "周教授"})
        self.assertEqual(len(board.relationships), 1)
        self.assertFalse(board.relationships_inferred, "the graph shows the settled relation, not co-occurrence")
        self.assertTrue(board.overview.synopsis or board.overview.genre, "the overview is on the board too")

        # 2) 分集账本按已定的角色和关系规划。
        inventory_at = next(i for i, text in enumerate(gateway.prompts) if "relationships" in text and "characters" in text and "分集规划师" not in text)
        ledger_at = next(i for i, text in enumerate(gateway.prompts) if "分集规划师" in text)
        self.assertLess(inventory_at, ledger_at, "the cast is extracted before the ledger is planned")
        ledger_prompt = gateway.prompts[ledger_at]
        self.assertIn("角色与人物关系", ledger_prompt)
        self.assertIn("林夏（女主角）", ledger_prompt)
        self.assertIn(RELATION, ledger_prompt)

        # 3) 完整剧本逐集撰写时，分场与正文都带着这些关系。
        gateway.release.set()
        _wait_for(self.repo, script_detail.DONE)
        episode_prompts = [text for text in gateway.prompts if "<relationships>" in text]
        self.assertTrue(any("当前正在生成第" in text for text in episode_prompts), "the scene plan carries the relationships")
        self.assertTrue(any("小说体剧本正文" in text for text in episode_prompts), "the prose carries the relationships")
        self.assertTrue(all(RELATION in text for text in episode_prompts))


class RelationshipPromptTests(unittest.TestCase):
    def test_no_relationships_leaves_the_prompts_as_they_were(self):
        self.assertEqual(prompts._relationships_block([]), "")
        self.assertEqual(prompts._ledger_cast_lines(None), [])
        self.assertEqual(prompts._ledger_cast_lines({"characters": {}, "relationships": []}), [])

    def test_relations_are_kept_only_for_the_people_in_the_episode(self):
        relations = [
            {"from": "沈砚", "to": "林晚", "relation": "暗恋", "bidirectional": False},
            {"from": "赵恒", "to": "老周", "relation": "主仆", "bidirectional": False},
        ]
        block = prompts._relationships_block(relations, ["沈砚", "林晚"])
        self.assertIn("沈砚 → 林晚：暗恋", block)
        self.assertNotIn("主仆", block)


if __name__ == "__main__":
    unittest.main()
