# -*- coding: utf-8 -*-
import re
from pydantic import BaseModel, Field, field_validator
from typing import Optional

from app import settings
from app.core import prompt_data


_WORDING_FILE = "schema_auth"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/schema_auth.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)

EMAIL_REGEX = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"

class RegisterRequest(BaseModel):
    """
    用户注册数据模型
    """
    email: Optional[str] = Field(None, description=_text_of("RegisterRequest.description"))
    phone: Optional[str] = Field(None, description=_text_of("RegisterRequest.description.2"))
    password: str = Field(
        ...,
        min_length=settings.PASSWORD_MIN_LENGTH,
        max_length=settings.PASSWORD_MAX_LENGTH,
        description=_text_of("RegisterRequest.description.3").format(settings.PASSWORD_MIN_LENGTH),
    )

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not re.match(EMAIL_REGEX, v):
                raise ValueError(_text_of("validate_email.text"))
        return v

class PasswordLoginRequest(BaseModel):
    """
    账号密码登录数据模型 (支持手机号或邮箱登录)
    """
    login_id: str = Field(..., description=_text_of("PasswordLoginRequest.description"))
    password: str = Field(..., description=_text_of("PasswordLoginRequest.description.2"))

class SendCodeRequest(BaseModel):
    """
    发送登录验证码请求模型
    """
    login_id: str = Field(..., description=_text_of("SendCodeRequest.description"))

class CodeLoginRequest(BaseModel):
    """
    验证码登录数据模型
    """
    login_id: str = Field(..., description=_text_of("CodeLoginRequest.description"))
    code: str = Field(..., description=_text_of("CodeLoginRequest.description.2"))
