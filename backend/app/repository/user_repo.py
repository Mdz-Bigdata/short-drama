# -*- coding: utf-8 -*-
import os
import json
import hashlib
import uuid
from typing import Optional, Dict, Any, List

class UserRepository:
    """
    轻量级 JSON 用户持久化仓储类 (Repository)
    """
    def __init__(self, db_path: str = "/Users/mindezhi/short-drama/backend/users_db.json"):
        self.db_path = db_path
        # 确保文件及默认用户存在
        if not os.path.exists(self.db_path) or os.path.getsize(self.db_path) < 5:
            self._init_default_db()

    def _init_default_db(self) -> None:
        """
        初始化默认用户数据库，置入演示账号
        """
        # 预设超级管理员：密码为 admin123
        salt = "novara_default_salt_998"
        password_hash = hashlib.sha256(("admin123" + salt).encode('utf-8')).hexdigest()
        
        default_user = {
            "user_id": "admin_user_id_100",
            "email": "admin@example.com",
            "phone": "13800000000",
            "password_hash": password_hash,
            "salt": salt,
            "username": "管理员"
        }
        
        initial_data = {
            "admin_user_id_100": default_user
        }
        self._write_db(initial_data)

    def _read_db(self) -> Dict[str, Any]:
        try:
            with open(self.db_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _write_db(self, data: Dict[str, Any]) -> None:
        with open(self.db_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    def create_user(self, email: Optional[str], phone: Optional[str], password_plain: str) -> Dict[str, Any]:
        """
        创建一个新用户并持久化
        """
        db = self._read_db()
        user_id = str(uuid.uuid4())
        salt = os.urandom(16).hex()
        password_hash = hashlib.sha256((password_plain + salt).encode('utf-8')).hexdigest()
        
        user_data = {
            "user_id": user_id,
            "email": email.strip() if email else None,
            "phone": phone.strip() if phone else None,
            "password_hash": password_hash,
            "salt": salt,
            "username": email.split("@")[0] if email else (phone[-4:] if phone else "用户")
        }
        db[user_id] = user_data
        self._write_db(db)
        return user_data

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """
        根据邮箱查找用户
        """
        db = self._read_db()
        email_clean = email.strip().lower()
        for user in db.values():
            if user.get("email") and user["email"].strip().lower() == email_clean:
                return user
        return None

    def get_user_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        """
        根据手机号查找用户
        """
        db = self._read_db()
        phone_clean = phone.strip()
        for user in db.values():
            if user.get("phone") and user["phone"].strip() == phone_clean:
                return user
        return None

    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        根据用户唯一 ID 查找用户
        """
        db = self._read_db()
        return db.get(user_id)
