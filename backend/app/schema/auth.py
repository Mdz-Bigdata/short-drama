# -*- coding: utf-8 -*-
import re
from pydantic import BaseModel, Field, field_validator
from typing import Optional

EMAIL_REGEX = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"

class RegisterRequest(BaseModel):
    """
    用户注册数据模型
    """
    email: Optional[str] = Field(None, description="注册绑定的邮箱")
    phone: Optional[str] = Field(None, description="注册绑定的手机号")
    password: str = Field(..., min_length=6, description="密码，最少 6 位字符")

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not re.match(EMAIL_REGEX, v):
                raise ValueError("邮箱格式不正确")
        return v

class PasswordLoginRequest(BaseModel):
    """
    账号密码登录数据模型 (支持手机号或邮箱登录)
    """
    login_id: str = Field(..., description="登录账号，支持邮箱或手机号")
    password: str = Field(..., description="登录密码")

class SendCodeRequest(BaseModel):
    """
    发送登录验证码请求模型
    """
    login_id: str = Field(..., description="接收验证码的邮箱或手机号")

class CodeLoginRequest(BaseModel):
    """
    验证码登录数据模型
    """
    login_id: str = Field(..., description="登录所用的邮箱或手机号")
    code: str = Field(..., description="接收到的 6 位验证码")

