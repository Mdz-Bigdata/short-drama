# -*- coding: utf-8 -*-
# ruff: noqa: E402
import os
import posixpath
import logging
import uvicorn
from pathlib import Path
from dotenv import load_dotenv

# Load the server-only environment before importing routers and provider services.
load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

# Application loggers emit structured task events through the root handler.
# Provider secrets and request bodies are intentionally never included.
_log_level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)
logging.basicConfig(
    level=_log_level,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.api.drama_api import router as drama_router
from app.api.auth_api import router as auth_router
from app.api.production_api import router as production_router
from app.api.project_skill_api import router as project_skill_router
from app.api.studio_api import router as studio_router
from app.api.agent_api import router as agent_router
from app.api.billing_api import router as billing_router
from app.api.element_api import router as element_router
from app.api.platform_api import router as platform_router
from app.api.model_configuration_api import router as model_configuration_router
from app.api.user_api import router as user_router
from app.core.media_compositor import MEDIA_DIR
from app.repository.task_repo import TaskStoreUnavailableError
from app.platform.bootstrap import initialize_platform
from app.platform.dependencies import get_model_secret_cipher, get_platform_store
from app.platform.request_limits import ElementUploadGuardMiddleware, ScriptUpdateGuardMiddleware
from app.platform.runtime_models import hydrate_runtime_model_registry
from app.platform.runtime_skills import hydrate_runtime_skill_registry

app = FastAPI(
    title="AI短剧 8-Agent 工业化协同成片系统",
    description="支持一键成片与步骤式断点续传的 AI 短剧/漫剧生成管理后端",
    version="1.0.0"
)

_allowed_origins = [
    item.strip() for item in os.getenv(
        "ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",") if item.strip()
]

app.add_middleware(ElementUploadGuardMiddleware)
app.add_middleware(ScriptUpdateGuardMiddleware)

# 允许跨域请求 CORS (由于需要带凭证Cookie，allow_origins不能使用"*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _security_boundary(request: Request, call_next):
    origin = request.headers.get("origin")
    # StaticFiles normalizes duplicate slashes and dot segments before opening
    # a file. Apply the same normalization to the percent-decoded ASGI path so
    # legacy private element images cannot bypass this boundary.
    normalized_path = posixpath.normpath(
        "/" + request.url.path.replace("\\", "/").lstrip("/")
    )
    normalized_path_key = normalized_path.casefold()
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and origin and origin not in _allowed_origins:
        response = JSONResponse(status_code=403, content={"detail": "请求来源不受信任"})
    elif (
        normalized_path_key == "/media/elements"
        or normalized_path_key.startswith("/media/elements/")
    ):
        # Element reference images are account-private. Keep the general
        # /media mount for generated audio/video, but never let its static
        # handler bypass the authenticated element file endpoint.
        response = JSONResponse(status_code=404, content={"detail": "Not Found"})
    else:
        response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    if (os.getenv("ENVIRONMENT") or "development").lower() in {"prod", "production"}:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

@app.exception_handler(TaskStoreUnavailableError)
async def _task_store_unavailable(request: Request, exc: TaskStoreUnavailableError):
    """Report a broken task store honestly instead of as a missing project."""
    logging.getLogger("app.main").error("任务库不可用: %s", exc)
    return JSONResponse(
        status_code=503,
        content={"detail": "任务库暂时不可用，已阻止写入以避免数据丢失，请检查服务端存储后重试"},
    )


# 挂载本地生成媒体的静态访问路由 (TTS 配音、合成成片)
os.makedirs(MEDIA_DIR, exist_ok=True)
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")

# 挂载 API 路由
app.include_router(drama_router)
app.include_router(auth_router)
app.include_router(production_router)
app.include_router(studio_router)
app.include_router(agent_router)
app.include_router(platform_router)
app.include_router(model_configuration_router)
app.include_router(element_router)
app.include_router(user_router)
app.include_router(billing_router)
app.include_router(project_skill_router)


@app.on_event("startup")
async def _initialize_postgresql_platform():
    import logging
    result = await initialize_platform(get_platform_store())
    if result.get("admin_created"):
        logging.getLogger("main").warning(
            "One-time administrator created; credential path=%s",
            result.get("credential_file"),
        )
    await hydrate_runtime_model_registry(get_platform_store(), get_model_secret_cipher())
    await hydrate_runtime_skill_registry(get_platform_store())

def _recover_orphan_task_state(task: dict) -> bool:
    """Normalize a persisted running task after a process restart."""
    if task.get("status") != "running" or not task.get("task_id"):
        return False

    progress = task.get("stage_progress")
    if isinstance(progress, dict) and progress.get("status") == "success":
        # A stage can finish while the historical task-level status remains
        # running. It is complete and merely waiting for the next stage.
        task["status"] = "idle"
        task["fail_reason"] = None
    else:
        task["status"] = "interrupted"
        task["fail_reason"] = "服务重启导致后台任务中断，可点击恢复(/resume)从断点续跑"
    return True


@app.on_event("startup")
def _recover_orphan_tasks():
    """
    服务启动时回收孤儿任务 (防孤儿)：一键成片走 FastAPI BackgroundTasks，
    若服务在生成途中重启/崩溃，任务会永久卡在 running。启动时把真正未完成的运行态
    重置为 interrupted；阶段进度已经成功的任务恢复为 idle，等待下一阶段。
    """
    import logging
    log = logging.getLogger("main")
    try:
        from app.repository.task_repo import TaskRepository
        repo = TaskRepository()
        n = 0
        for t in repo.list_all_tasks():
            if isinstance(t, dict) and _recover_orphan_task_state(t):
                repo.save_task(t["task_id"], t)
                n += 1
        if n:
            log.warning(f"[启动恢复] 已规范化 {n} 个残留 running 任务的状态")
    except Exception as e:
        log.error(f"[启动恢复] 孤儿任务回收失败: {str(e)[:160]}")


@app.get("/")
def read_root():
    return {
        "status": "online",
        "message": "AI Short Drama 8-Agent Backend Server is running successfully."
    }

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
