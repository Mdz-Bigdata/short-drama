# -*- coding: utf-8 -*-
import os
import json
from typing import Optional, List, Dict, Any

class TaskRepository:
    """
    轻量级 JSON 任务状态仓储类 (Repository)，保证断点状态持久化
    """
    def __init__(self, db_path: str = "/Users/mindezhi/short-drama/backend/tasks_db.json"):
        """
        初始化仓储，指定 JSON 持久化文件路径
        """
        self.db_path = db_path
        # 确保持久化文件存在，如果不存在则初始化空字典
        if not os.path.exists(self.db_path):
            with open(self.db_path, "w", encoding="utf-8") as f:
                json.dump({}, f, ensure_ascii=False, indent=4)

    def _read_db(self) -> Dict[str, Any]:
        """
        内部辅助方法：读取数据库文件
        """
        try:
            with open(self.db_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _write_db(self, data: Dict[str, Any]) -> None:
        """
        内部辅助方法：写入数据库文件
        """
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    def save_task(self, task_id: str, task_data: Dict[str, Any]) -> None:
        """
        持久化保存任务状态及已生成的中间资产
        """
        db = self._read_db()
        db[task_id] = task_data
        self._write_db(db)

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        """
        根据任务唯一 ID 获取任务状态
        """
        db = self._read_db()
        return db.get(task_id)

    def list_all_tasks(self) -> List[Dict[str, Any]]:
        """
        获取当前存储的所有短剧任务列表
        """
        db = self._read_db()
        return list(db.values())

    def delete_task(self, task_id: str) -> bool:
        """
        根据任务唯一 ID 从数据库中删除任务
        """
        db = self._read_db()
        if task_id in db:
            db.pop(task_id)
            self._write_db(db)
            return True
        return False

