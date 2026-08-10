import os
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.repository.user_repo import UserRepository
from app.service.auth_service import AuthService, MOCK_CODES_DB, _CODE_SEND_AT


class AuthSecurityTests(unittest.TestCase):
    def setUp(self):
        MOCK_CODES_DB.clear()
        _CODE_SEND_AT.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.repo = UserRepository(str(Path(self.temp.name) / "users.json"))
        self.auth = AuthService(user_repo=self.repo)

    def tearDown(self):
        MOCK_CODES_DB.clear()
        _CODE_SEND_AT.clear()
        self.temp.cleanup()

    def test_new_database_has_no_default_admin_and_password_uses_scrypt(self):
        self.assertEqual(self.repo.list_users(), [])
        user = self.repo.create_user("user@example.com", None, "correct horse battery staple")
        self.assertTrue(user["password_hash"].startswith("scrypt$"))
        self.assertNotIn("correct horse", user["password_hash"])
        logged_in = self.auth.login_by_password("user@example.com", "correct horse battery staple")
        self.assertEqual(logged_in["user_id"], user["user_id"])

    def test_legacy_password_is_upgraded_after_successful_login(self):
        legacy_path = Path(self.temp.name) / "legacy.json"
        salt = "legacy-salt"
        digest = hashlib.sha256(("old-password" + salt).encode()).hexdigest()
        legacy_path.write_text(json.dumps({
            "legacy-user": {
                "user_id": "legacy-user", "email": "legacy@example.com", "phone": None,
                "password_hash": digest, "salt": salt, "username": "legacy",
            }
        }), encoding="utf-8")
        repo = UserRepository(str(legacy_path))
        AuthService(user_repo=repo).login_by_password("legacy@example.com", "old-password")
        upgraded = repo.get_user_by_id("legacy-user")
        self.assertTrue(upgraded["password_hash"].startswith("scrypt$"))
        self.assertNotIn("salt", upgraded)

    def test_session_token_has_expiry_and_rejects_expired_value(self):
        with patch("app.service.auth_service.time.time", return_value=1_000):
            token = self.auth.generate_token("user-1")
            self.assertEqual(len(token.split(".")), 3)
        with patch("app.service.auth_service.time.time", return_value=1_400), patch.dict(
            os.environ, {"AUTH_SESSION_TTL_SECONDS": "300"}
        ):
            self.assertIsNone(self.auth.verify_token(token))

    def test_mock_code_requires_explicit_dev_flags_and_is_one_time(self):
        with patch.dict(os.environ, {"AUTH_MOCK_CODES": "1", "AUTH_EXPOSE_MOCK_CODE": "1"}, clear=False):
            success, code = self.auth.send_verification_code("new@example.com")
            self.assertTrue(success)
            self.assertRegex(code, r"^\d{6}$")
            self.assertNotEqual(MOCK_CODES_DB["new@example.com"]["digest"], code)
            first = self.auth.login_by_code("new@example.com", code)
            self.assertEqual(first["email"], "new@example.com")
            with self.assertRaises(ValueError):
                self.auth.login_by_code("new@example.com", code)


if __name__ == "__main__":
    unittest.main()
