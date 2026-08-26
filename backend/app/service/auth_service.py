# -*- coding: utf-8 -*-
import os
import hmac
import hashlib
import secrets
import time
import re
import logging
from typing import Optional, Dict, Tuple, Any
from app.repository.user_repo import UserRepository, verify_password

logger = logging.getLogger("app.service.auth_service")

# Only a keyed digest is retained; plaintext codes are never stored.
MOCK_CODES_DB: Dict[str, Dict[str, Any]] = {}
_CODE_SEND_AT: Dict[str, float] = {}
_DEV_SESSION_SECRET = secrets.token_bytes(32)


def _session_secret() -> bytes:
    configured = (os.getenv("AUTH_SIGNING_SECRET") or "").strip()
    if configured:
        if len(configured) < 32:
            raise RuntimeError("AUTH_SIGNING_SECRET must contain at least 32 characters")
        return configured.encode("utf-8")
    if (os.getenv("ENVIRONMENT") or "development").lower() in {"prod", "production"}:
        raise RuntimeError("AUTH_SIGNING_SECRET is required in production")
    return _DEV_SESSION_SECRET


def _code_digest(login_id: str, code: str) -> str:
    return hmac.new(_session_secret(), f"{login_id}\0{code}".encode("utf-8"), hashlib.sha256).hexdigest()


def verify_session_token(token: str) -> Optional[str]:
    """Validate a signed session cookie without constructing a repository."""
    if not token:
        return None
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        user_id, issued_at_text, signature = parts
        issued_at = int(issued_at_text)
        ttl = max(300, min(2_592_000, int(os.getenv("AUTH_SESSION_TTL_SECONDS", "86400"))))
        now = int(time.time())
        if issued_at > now + 60 or now - issued_at > ttl:
            return None
        payload = f"{user_id}.{issued_at_text}"
        expected_sig = hmac.new(_session_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        return user_id if hmac.compare_digest(signature, expected_sig) else None
    except (ValueError, TypeError, RuntimeError):
        return None

class AuthService:
    """
    用户登录注册与身份签名业务服务类 (Service)
    """
    def __init__(self, user_repo: UserRepository | None = None):
        self.user_repo = user_repo or UserRepository()

    def generate_token(self, user_id: str) -> str:
        """
        根据用户 ID 生成带 HMAC-SHA256 签名的防篡改 Token，用于 HttpOnly Cookie 存储
        """
        issued_at = str(int(time.time()))
        payload = f"{user_id}.{issued_at}"
        signature = hmac.new(_session_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{payload}.{signature}"

    def verify_token(self, token: str) -> Optional[str]:
        """
        验证 Token 签名是否合法，如果合法返回解析出的 user_id，否则返回 None
        """
        return verify_session_token(token)

    def _send_ali_sms(self, phone: str, code: str) -> bool:
        """
        调用阿里云短信服务发送真实的验证码
        """
        access_key_id = os.getenv("ALIBABA_CLOUD_ACCESS_KEY_ID")
        access_key_secret = os.getenv("ALIBABA_CLOUD_ACCESS_KEY_SECRET")
        sign_name = os.getenv("ALIBABA_CLOUD_SMS_SIGN_NAME")
        template_code = os.getenv("ALIBABA_CLOUD_SMS_TEMPLATE_CODE")
        
        if not all([access_key_id, access_key_secret, sign_name, template_code]):
            logger.warning("[AuthService] 阿里云短信配置不完整，将降级至 Mock 发送")
            return False
            
        try:
            from alibabacloud_dysmsapi20170525.client import Client as DysmsapiClient
            from alibabacloud_tea_openapi import models as open_api_models
            from alibabacloud_dysmsapi20170525 import models as dysmsapi_models
            
            config = open_api_models.Config(
                access_key_id=access_key_id,
                access_key_secret=access_key_secret
            )
            config.endpoint = "dysmsapi.aliyuncs.com"
            client = DysmsapiClient(config)
            
            send_sms_request = dysmsapi_models.SendSmsRequest(
                phone_numbers=phone,
                sign_name=sign_name,
                template_code=template_code,
                template_param=f'{{"code":"{code}"}}'
            )
            
            response = client.send_sms(send_sms_request)
            
            if response.body.code == "OK":
                logger.info(f"[AuthService] 阿里云短信成功发送至 {phone}，短信 RequestId: {response.body.request_id}")
                return True
            else:
                logger.error(f"[AuthService] 阿里云短信发送失败，错误码: {response.body.code}, 消息: {response.body.message}")
                return False
        except Exception as e:
            logger.error(f"[AuthService] 调用阿里云短信接口发生异常: {type(e).__name__}")
            return False

    def send_verification_code(self, login_id: str) -> Tuple[bool, str]:
        """
        发送 6 位数字验证码。
        若是手机号，尝试调用阿里云短信服务；若失败或非手机号，则走降级 Mock 通道。
        """
        login_id_clean = login_id.strip()
        if not login_id_clean:
            return False, ""
        now = time.monotonic()
        cooldown = max(10, min(300, int(os.getenv("AUTH_CODE_COOLDOWN_SECONDS", "60"))))
        if now - _CODE_SEND_AT.get(login_id_clean, 0) < cooldown:
            return False, ""
        _CODE_SEND_AT[login_id_clean] = now
            
        # Cryptographically strong six-digit code with a short expiry.
        code = f"{secrets.randbelow(900000) + 100000}"
        
        # 判断是否是手机号
        is_phone = re.match(r"^1[3-9]\d{9}$", login_id_clean) is not None
        sms_sent = False
        
        if is_phone:
            sms_sent = self._send_ali_sms(login_id_clean, code)

        mock_enabled = os.getenv("AUTH_MOCK_CODES", "0") == "1" and (
            os.getenv("ENVIRONMENT") or "development"
        ).lower() not in {"prod", "production"}
        if not sms_sent and not mock_enabled:
            return False, ""

        ttl = max(60, min(900, int(os.getenv("AUTH_CODE_TTL_SECONDS", "300"))))
        MOCK_CODES_DB[login_id_clean] = {
            "digest": _code_digest(login_id_clean, code),
            "expires_at": int(time.time()) + ttl,
            "attempts": 0,
        }
        expose = mock_enabled and os.getenv("AUTH_EXPOSE_MOCK_CODE", "0") == "1"
        return True, code if expose else ""


    def register(self, email: Optional[str], phone: Optional[str], password_plain: str) -> Dict[str, Any]:
        """
        用户注册账号密码
        """
        if email:
            existing = self.user_repo.get_user_by_email(email)
            if existing:
                raise ValueError("该邮箱已被注册")
        if phone:
            existing = self.user_repo.get_user_by_phone(phone)
            if existing:
                raise ValueError("该手机号已被注册")
                
        user = self.user_repo.create_user(email, phone, password_plain)
        return {
            "user_id": user["user_id"],
            "username": user["username"],
            "email": user["email"],
            "phone": user["phone"]
        }

    def login_by_password(self, login_id: str, password_plain: str) -> Dict[str, Any]:
        """
        账号密码登录 (支持邮箱或手机号登录)
        """
        login_id_clean = login_id.strip()
        user = None
        
        # 简单正则判定输入的是邮箱还是手机号
        if "@" in login_id_clean:
            user = self.user_repo.get_user_by_email(login_id_clean)
        else:
            user = self.user_repo.get_user_by_phone(login_id_clean)
            
        if not user:
            raise ValueError("账号或密码错误")
        if (
            user.get("user_id") == "admin_user_id_100"
            and user.get("email") == "admin@example.com"
            and os.getenv("AUTH_ALLOW_LEGACY_ADMIN", "0") != "1"
        ):
            raise ValueError("内置演示管理员已禁用，请注册独立账号")
            
        encoded = str(user.get("password_hash") or "")
        if not verify_password(password_plain, encoded, user.get("salt")):
            raise ValueError("账号或密码错误")
        if not encoded.startswith("scrypt$"):
            self.user_repo.upgrade_password(user["user_id"], password_plain)
            
        return {
            "user_id": user["user_id"],
            "username": user["username"],
            "email": user["email"],
            "phone": user["phone"]
        }

    def login_by_code(self, login_id: str, code: str) -> Dict[str, Any]:
        """
        手机/邮箱验证码登录。如果手机/邮箱尚未注册，系统会自动为其创建新用户 (快捷登录注册一体化)
        """
        login_id_clean = self.consume_verification_code(login_id, code)
        
        # 判断是邮箱还是手机，并查找用户
        user = None
        is_email = "@" in login_id_clean
        if is_email:
            user = self.user_repo.get_user_by_email(login_id_clean)
        else:
            user = self.user_repo.get_user_by_phone(login_id_clean)
            
        # 若用户不存在，直接注册为新用户 (默认空密码或自动生成随机密码)
        if not user:
            random_pw = os.urandom(12).hex()
            email_param = login_id_clean if is_email else None
            phone_param = None if is_email else login_id_clean
            user = self.user_repo.create_user(email_param, phone_param, random_pw)
            logger.info(f"[AuthService] 验证码登录成功，系统自动为新用户注册: {login_id_clean}")
            
        return {
            "user_id": user["user_id"],
            "username": user["username"],
            "email": user["email"],
            "phone": user["phone"]
        }

    def consume_verification_code(self, login_id: str, code: str) -> str:
        """Validate and consume a one-time login code without choosing persistence."""
        login_id_clean = login_id.strip()
        code_clean = code.strip()
        if not login_id_clean or not code_clean:
            raise ValueError("参数不能为空")
        saved = MOCK_CODES_DB.get(login_id_clean)
        if not saved or int(saved.get("expires_at", 0)) < int(time.time()):
            MOCK_CODES_DB.pop(login_id_clean, None)
            raise ValueError("验证码不正确或已过期")
        saved["attempts"] = int(saved.get("attempts", 0)) + 1
        if saved["attempts"] > 5:
            MOCK_CODES_DB.pop(login_id_clean, None)
            raise ValueError("验证码不正确或已过期")
        supplied = _code_digest(login_id_clean, code_clean)
        if not hmac.compare_digest(str(saved.get("digest") or ""), supplied):
            raise ValueError("验证码不正确或已过期")
        MOCK_CODES_DB.pop(login_id_clean, None)
        return login_id_clean
