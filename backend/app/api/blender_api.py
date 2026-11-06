# -*- coding: utf-8 -*-
"""Blender 3D 预演台的全局入口：本机 Blender 状态与实时桥接插件下载。场景级操作在 drama_api 里。"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse

from app.api.auth_api import get_current_user
from app.core.blender_previz import runner
from app.service import blender_previz_service

router = APIRouter(prefix="/api/blender", tags=["Blender Previz"], dependencies=[Depends(get_current_user)])


@router.get("/status")
async def blender_status():
    """本机有没有 Blender、版本号，以及打开的 Blender 是否已连上桥接插件。"""
    return await run_in_threadpool(blender_previz_service.status)


@router.get("/addon.zip")
def download_addon():
    """实时桥接插件：在 Blender 偏好设置 › 插件 › 从磁盘安装 里选这个 zip。"""
    target = Path(tempfile.gettempdir()) / "short_drama_previz.zip"
    runner.addon_zip(target)
    return FileResponse(target, media_type="application/zip", filename="short_drama_previz.zip")
