# -*- coding: utf-8 -*-
from fastapi import APIRouter, HTTPException, Response, Depends, Cookie
from typing import Dict, Any, Optional
from app.schema.auth import RegisterRequest, PasswordLoginRequest, SendCodeRequest, CodeLoginRequest
from app.service.auth_service import AuthService
from app.repository.user_repo import UserRepository

router = APIRouter(prefix="/api/auth", tags=["用户身份认证"])
auth_service = AuthService()
user_repo = UserRepository()

def get_current_user(auth_token: Optional[str] = Cookie(None)):
    """
    FastAPI 依赖注入：从 HttpOnly Cookie 中提取并校验 Token
    敏感操作必须依赖此方法进行身份鉴权
    """
    if not auth_token:
        raise HTTPException(status_code=401, detail="未登录，请先登录")
    user_id = auth_service.verify_token(auth_token)
    if not user_id:
        raise HTTPException(status_code=401, detail="会话已过期，请重新登录")
    user = user_repo.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="用户账户不存在")
    return user

@router.post("/send_code")
def send_code(req: SendCodeRequest):
    """
    发送手机/邮箱登录验证码 (本地 Mock 发送，在响应体和日志中回显方便测试)
    """
    login_id = req.login_id.strip()
    if not login_id:
        raise HTTPException(status_code=400, detail="邮箱或手机号不能为空")
    
    success, code = auth_service.send_verification_code(login_id)
    if not success:
        raise HTTPException(status_code=500, detail="模拟验证码发送失败")
        
    return {
        "status": "success",
        "message": f"验证码已成功发送至 {login_id}",
        "code": code  # 前端回显，提供零摩擦测试体验
    }

@router.post("/register")
def register_user(req: RegisterRequest):
    """
    用户注册账号密码
    """
    if not req.email and not req.phone:
        raise HTTPException(status_code=400, detail="注册必须提供邮箱或手机号")
    try:
        user_info = auth_service.register(req.email, req.phone, req.password)
        return {"status": "success", "user": user_info}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"注册失败: {str(e)}")

@router.post("/login_password")
def login_by_password(req: PasswordLoginRequest, response: Response):
    """
    账号密码登录 (写入 HttpOnly Cookie)
    """
    try:
        user_info = auth_service.login_by_password(req.login_id, req.password)
        # 生成防篡改 Token 并写入 Cookie
        token = auth_service.generate_token(user_info["user_id"])
        response.set_cookie(
            key="auth_token",
            value=token,
            httponly=True,
            samesite="lax",
            max_age=86400,  # 1天
            secure=False    # 本地非 HTTPS 环境设为 False 才能正常传递
        )
        return {"status": "success", "user": user_info}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"登录失败: {str(e)}")

@router.post("/login_code")
def login_by_code(req: CodeLoginRequest, response: Response):
    """
    手机/邮箱验证码快捷登录 (写入 HttpOnly Cookie，自动注册新用户)
    """
    try:
        user_info = auth_service.login_by_code(req.login_id, req.code)
        # 生成防篡改 Token 并写入 Cookie
        token = auth_service.generate_token(user_info["user_id"])
        response.set_cookie(
            key="auth_token",
            value=token,
            httponly=True,
            samesite="lax",
            max_age=86400,  # 1天
            secure=False
        )
        return {"status": "success", "user": user_info}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"登录失败: {str(e)}")

@router.get("/me")
def get_user_profile(current_user: dict = Depends(get_current_user)):
    """
    获取当前登录用户信息 (用于前端初始登录态探测)
    """
    return {
        "status": "success",
        "user": {
            "user_id": current_user["user_id"],
            "username": current_user["username"],
            "email": current_user.get("email"),
            "phone": current_user.get("phone")
        }
    }

@router.post("/logout")
def logout_user(response: Response):
    """
    注销登录 (清除 HttpOnly Cookie)
    """
    response.delete_cookie(
        key="auth_token",
        samesite="lax",
        httponly=True,
        secure=False
    )
    return {"status": "success", "message": "已成功退出登录"}
