# -*- coding: utf-8 -*-
from __future__ import annotations

import secrets
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response

from app import settings
from app.ingest.parsers import SourceIngestor
from app.platform.bootstrap import development_admin_login_hint
from app.platform.dependencies import get_platform_store
from app.platform.models import PlatformUser
from app.platform.store import PlatformStore
from app.schema.drama import DEFAULT_EPISODE_COUNT, EPISODE_COUNT_MAX, EPISODE_COUNT_MIN
from app.schema.auth import CodeLoginRequest, PasswordLoginRequest, RegisterRequest, SendCodeRequest
from app.service.auth_service import AuthService


router = APIRouter(prefix="/api/auth", tags=["用户身份认证"])
auth_service = AuthService()


def _public_user(user: PlatformUser) -> dict:
    return {
        "user_id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
        "phone": user.phone,
        "role": user.role,
        "status": user.status,
        "must_change_password": user.must_change_password,
    }


async def get_current_user(
    auth_token: Optional[str] = Cookie(None, alias=settings.AUTH_COOKIE_NAME),
    store: PlatformStore = Depends(get_platform_store),
) -> dict:
    if not auth_token:
        raise HTTPException(status_code=401, detail="未登录，请先登录")
    user_id = auth_service.verify_token(auth_token)
    if not user_id:
        raise HTTPException(status_code=401, detail="会话已过期，请重新登录")
    user = await store.get_user(user_id)
    if not user or user.status != "active":
        raise HTTPException(status_code=401, detail="用户账户不存在或已停用")
    return _public_user(user)


async def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    if current_user.get("must_change_password"):
        raise HTTPException(status_code=403, detail="首次登录必须先在用户中心修改管理员密码")
    return current_user


def _client_config() -> dict:
    """Limits the browser must agree with the server on, sent with the session instead of copied into the UI."""
    return {
        "password_min_length": settings.PASSWORD_MIN_LENGTH,
        "verification_code": {
            "length": settings.VERIFICATION_CODE_LENGTH,
            "cooldown_seconds": settings.code_cooldown_seconds(),
        },
        "episode_count": {
            "min": EPISODE_COUNT_MIN,
            "max": EPISODE_COUNT_MAX,
            "default": DEFAULT_EPISODE_COUNT,
        },
        "script_upload": {
            "max_bytes": SourceIngestor.MAX_BYTES,
            "extensions": [f".{extension}" for extension in SourceIngestor.SUPPORTED_EXTENSIONS],
        },
    }


def _set_session(response: Response, user_id: str) -> None:
    response.set_cookie(
        key=settings.AUTH_COOKIE_NAME,
        value=auth_service.generate_token(user_id),
        httponly=True,
        samesite="lax",
        # The cookie lives exactly as long as the signed token inside it stays valid.
        max_age=settings.session_ttl_seconds(),
        secure=settings.cookie_secure(),
        path="/",
    )


@router.post("/send_code")
def send_code(req: SendCodeRequest):
    login_id = req.login_id.strip()
    if not login_id:
        raise HTTPException(status_code=400, detail="邮箱或手机号不能为空")
    success, development_code = auth_service.send_verification_code(login_id)
    if not success:
        raise HTTPException(status_code=503, detail="验证码发送服务暂不可用")
    payload = {
        "status": "success",
        "message": f"验证码已成功发送至 {login_id}",
        "cooldown_seconds": settings.code_cooldown_seconds(),
    }
    if development_code:
        payload["development_code"] = development_code
    return payload


@router.post("/register")
async def register_user(req: RegisterRequest, store: PlatformStore = Depends(get_platform_store)):
    try:
        user, created = await store.create_user(
            email=req.email,
            phone=req.phone,
            password=req.password,
        )
        if not created:
            raise HTTPException(status_code=409, detail="邮箱或手机号已被注册")
        return {"status": "success", "user": _public_user(user)}
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/login_password")
async def login_by_password(
    req: PasswordLoginRequest,
    response: Response,
    store: PlatformStore = Depends(get_platform_store),
):
    user = await store.verify_login(req.login_id, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="账号或密码错误")
    _set_session(response, user.id)
    return {"status": "success", "user": _public_user(user)}


@router.post("/login_code")
async def login_by_code(
    req: CodeLoginRequest,
    response: Response,
    store: PlatformStore = Depends(get_platform_store),
):
    try:
        login_id = auth_service.consume_verification_code(req.login_id, req.code)
        user = await store.get_user_by_login(login_id)
        if not user:
            random_password = secrets.token_urlsafe(24)
            user, _ = await store.create_user(
                email=login_id if "@" in login_id else None,
                phone=None if "@" in login_id else login_id,
                password=random_password,
            )
        _set_session(response, user.id)
        return {"status": "success", "user": _public_user(user)}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/me")
async def get_user_profile(current_user: dict = Depends(get_current_user)):
    return {"status": "success", "user": current_user}


@router.get("/session")
async def session_status(
    auth_token: Optional[str] = Cookie(None, alias=settings.AUTH_COOKIE_NAME),
    store: PlatformStore = Depends(get_platform_store),
):
    """Return a quiet browser bootstrap status without turning logged-out state into a console error."""
    # Local development shows which administrator the server bootstrapped; the
    # hint is absent in production and whenever bootstrapping is switched off.
    client_config = _client_config()
    signed_out = {
        "authenticated": False,
        "user": None,
        "bootstrap_admin_login": development_admin_login_hint(),
        "client_config": client_config,
    }
    user_id = auth_service.verify_token(auth_token or "")
    if not user_id:
        return signed_out
    user = await store.get_user(user_id)
    if not user or user.status != "active":
        return signed_out
    return {"authenticated": True, "user": _public_user(user), "client_config": client_config}


@router.post("/logout")
def logout_user(response: Response):
    response.delete_cookie(
        key=settings.AUTH_COOKIE_NAME,
        samesite="lax",
        httponly=True,
        secure=settings.cookie_secure(),
        path="/",
    )
    return {"status": "success", "message": "已成功退出登录"}
