# -*- coding: utf-8 -*-
"""Small local user repository with versioned scrypt password hashes."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_WRITE_LOCK = threading.RLock()


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("密码不能为空")
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt,
        n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=32,
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str, legacy_salt: str | None = None) -> bool:
    if encoded.startswith("scrypt$"):
        try:
            algorithm, n_value, r_value, p_value, salt_hex, digest_hex = encoded.split("$", 5)
            if algorithm != "scrypt":
                return False
            expected = bytes.fromhex(digest_hex)
            actual = hashlib.scrypt(
                password.encode("utf-8"), salt=bytes.fromhex(salt_hex),
                n=int(n_value), r=int(r_value), p=int(p_value), dklen=len(expected),
            )
            return hmac.compare_digest(actual, expected)
        except (ValueError, TypeError):
            return False
    # One-way compatibility for the prototype's salted SHA-256 records. A
    # successful login is immediately upgraded to scrypt by AuthService.
    if legacy_salt:
        legacy = hashlib.sha256((password + legacy_salt).encode("utf-8")).hexdigest()
        return hmac.compare_digest(legacy, encoded)
    return False


class UserRepository:
    """JSON remains a local-development boundary; writes are atomic."""

    def __init__(self, db_path: str | None = None):
        default_path = Path(__file__).resolve().parents[2] / "users_db.json"
        self.db_path = Path(db_path or os.getenv("USERS_DB_PATH") or default_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.db_path.exists() or self.db_path.stat().st_size < 2:
            self._write_db({})

    def _read_db(self) -> Dict[str, Any]:
        try:
            data = json.loads(self.db_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_db(self, data: Dict[str, Any]) -> None:
        with _WRITE_LOCK:
            temporary = self.db_path.with_suffix(self.db_path.suffix + ".tmp")
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")
            os.replace(temporary, self.db_path)

    def create_user(self, email: Optional[str], phone: Optional[str], password_plain: str) -> Dict[str, Any]:
        with _WRITE_LOCK:
            db = self._read_db()
            user_id = str(uuid.uuid4())
            user_data = {
                "user_id": user_id,
                "email": email.strip().lower() if email else None,
                "phone": phone.strip() if phone else None,
                "password_hash": hash_password(password_plain),
                "username": email.split("@")[0] if email else (phone[-4:] if phone else "用户"),
            }
            db[user_id] = user_data
            self._write_db(db)
            return user_data

    def upgrade_password(self, user_id: str, password_plain: str) -> None:
        with _WRITE_LOCK:
            db = self._read_db()
            user = db.get(user_id)
            if not isinstance(user, dict):
                raise ValueError("用户不存在")
            user["password_hash"] = hash_password(password_plain)
            user.pop("salt", None)
            self._write_db(db)

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        email_clean = email.strip().lower()
        return next((
            user for user in self._read_db().values()
            if isinstance(user.get("email"), str) and user["email"].strip().lower() == email_clean
        ), None)

    def get_user_by_phone(self, phone: str) -> Optional[Dict[str, Any]]:
        phone_clean = phone.strip()
        return next((
            user for user in self._read_db().values()
            if isinstance(user.get("phone"), str) and user["phone"].strip() == phone_clean
        ), None)

    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        return self._read_db().get(user_id)

    def list_users(self) -> List[Dict[str, Any]]:
        return list(self._read_db().values())
