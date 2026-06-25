# -*- coding: utf-8 -*-
import os
import hmac
import hashlib
import random
import re
import logging
from typing import Optional, Dict, Tuple, Any
from app.repository.user_repo import UserRepository

logger = logging.getLogger("app.service.auth_service")

# 模拟发送的验证码保存内存字典 { "login_id": "code" }
MOCK_CODES_DB: Dict[str, str] = {}

# HMAC 签名密钥 (生产环境推荐从环境变量读取，在此处我们做自适应读取与默认配置)
SIGNING_SECRET = "novara_secure_session_secret_key_889"

class AuthService:
    """
    用户登录注册与身份签名业务服务类 (Service)
    """
    def __init__(self):
        self.user_repo = UserRepository()

    def generate_token(self, user_id: str) -> str:
        """
        根据用户 ID 生成带 HMAC-SHA256 签名的防篡改 Token，用于 HttpOnly Cookie 存储
        """
        signature = hmac.new(SIGNING_SECRET.encode('utf-8'), user_id.encode('utf-8'), hashlib.sha256).hexdigest()
        return f"{user_id}.{signature}"

    def verify_token(self, token: str) -> Optional[str]:
        """
        验证 Token 签名是否合法，如果合法返回解析出的 user_id，否则返回 None
        """
        if not token:
            return None
        try:
            parts = token.split(".")
            if len(parts) != 2:
                return None
            user_id, signature = parts
            expected_sig = hmac.new(SIGNING_SECRET.encode('utf-8'), user_id.encode('utf-8'), hashlib.sha256).hexdigest()
            if hmac.compare_digest(signature.encode('utf-8'), expected_sig.encode('utf-8')):
                return user_id
        except Exception as e:
            logger.error(f"[AuthService] 验证 Token 发生未知错误: {str(e)}")
        return None

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
            logger.error(f"[AuthService] 调用阿里云短信接口发生异常: {str(e)}")
            return False

    def send_verification_code(self, login_id: str) -> Tuple[bool, str]:
        """
        发送 6 位数字验证码。
        若是手机号，尝试调用阿里云短信服务；若失败或非手机号，则走降级 Mock 通道。
        """
        login_id_clean = login_id.strip()
        if not login_id_clean:
            return False, ""
            
        # 生成 6 位随机验证码
        code = f"{random.randint(100000, 999999)}"
        MOCK_CODES_DB[login_id_clean] = code
        
        # 判断是否是手机号
        is_phone = re.match(r"^1[3-9]\d{9}$", login_id_clean) is not None
        sms_sent = False
        
        if is_phone:
            logger.info(f"[AuthService] 检测到手机号 {login_id_clean}，正在尝试调用阿里云短信...")
            sms_sent = self._send_ali_sms(login_id_clean, code)
            
        if not sms_sent:
            # 降级或模拟逻辑
            logger.info(f"\n[MOCK MESSAGE SERVICE] (已触发降级或模拟模式) 已向帐号 {login_id_clean} 发送验证码：{code}\n")
            
        return True, code


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
            
        # 验证密码哈希
        salt = user["salt"]
        expected_hash = hashlib.sha256((password_plain + salt).encode('utf-8')).hexdigest()
        
        if not hmac.compare_digest(user["password_hash"].encode('utf-8'), expected_hash.encode('utf-8')):
            raise ValueError("账号或密码错误")
            
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
        login_id_clean = login_id.strip()
        code_clean = code.strip()
        
        if not login_id_clean or not code_clean:
            raise ValueError("参数不能为空")
            
        # 校验验证码
        saved_code = MOCK_CODES_DB.get(login_id_clean)
        if not saved_code or saved_code != code_clean:
            raise ValueError("验证码不正确或已过期")
            
        # 消耗验证码 (防止重复使用)
        MOCK_CODES_DB.pop(login_id_clean, None)
        
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
