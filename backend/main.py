# -*- coding: utf-8 -*-
# ruff: noqa: E402
import asyncio
import os
import posixpath
import logging
import uvicorn
from pathlib import Path
from dotenv import load_dotenv

# Load the server-only environment before importing routers and provider services.
load_dotenv(Path(__file__).resolve().parent / ".env", override=False)

from app import settings

# Application loggers emit structured task events through the root handler.
# Provider secrets and request bodies are intentionally never included.
_log_level = getattr(logging, settings.log_level(), logging.INFO)
logging.basicConfig(
    level=_log_level,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.api.drama_api import router as drama_router
from app.api.blender_api import router as blender_router
from app.api.auth_api import router as auth_router
from app.api.production_api import router as production_router
from app.api.project_skill_api import router as project_skill_router
from app.api.director_desk_api import router as director_desk_router
from app.api.studio_api import router as studio_router
from app.api.agent_api import router as agent_router
from app.api.billing_api import router as billing_router
from app.api.finance_api import router as finance_router
from app.api.notification_api import router as notification_router
from app.api.poetry_api import router as poetry_router
from app.api.element_api import router as element_router
from app.api.platform_api import router as platform_router
from app.api.model_configuration_api import router as model_configuration_router
from app.api.user_api import router as user_router
from app.api.usage_admin_api import _tasks as usage_task_repository
from app.api.usage_admin_api import read_usage_records, router as usage_admin_router
from app.core import usage_ledger
from app import settings
from app.platform import payment_flow, reconciliation, usage_billing
from app.platform.billing_book import AccountGuard, BillingBook, active_book, set_account_watcher, set_active_book
from app.platform.billing_http import BillingRefusalMiddleware
from app.api.bgm_api import router as bgm_router
from app.api.mcp_api import router as mcp_router
from app.api.market_api import router as market_router
from app.api.task_center_api import router as task_center_router
from app.api.voice_asset_api import router as voice_asset_router
from app.api.image_pool_api import router as image_pool_router
from app.api.panorama_api import router as panorama_router
from app.api.recipe_api import router as recipe_router
from app.api.interactive_story_api import router as interactive_story_router
from app.api.canvas_workflow_api import router as canvas_workflow_router
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

_allowed_origins = settings.allowed_origins()

# Added first, so it sits innermost: a refused paid call becomes a 402 that still passes through CORS on its way out.
app.add_middleware(BillingRefusalMiddleware)
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
    private_element_media = f"{settings.MEDIA_ROUTE}/elements"
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and origin and origin not in _allowed_origins:
        response = JSONResponse(status_code=403, content={"detail": "请求来源不受信任"})
    elif (
        normalized_path_key == private_element_media
        or normalized_path_key.startswith(private_element_media + "/")
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
    if settings.is_production():
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
app.mount(settings.MEDIA_ROUTE, StaticFiles(directory=MEDIA_DIR), name="media")

# 挂载 API 路由
app.include_router(drama_router)
app.include_router(usage_admin_router)
app.include_router(blender_router)
app.include_router(auth_router)
app.include_router(production_router)
app.include_router(studio_router)
app.include_router(agent_router)
app.include_router(platform_router)
app.include_router(model_configuration_router)
app.include_router(element_router)
app.include_router(user_router)
app.include_router(billing_router)
app.include_router(finance_router)
app.include_router(notification_router)
app.include_router(poetry_router)
app.include_router(project_skill_router)
app.include_router(director_desk_router)
app.include_router(bgm_router)
app.include_router(mcp_router)
app.include_router(market_router)
app.include_router(task_center_router)
app.include_router(voice_asset_router)
app.include_router(image_pool_router)
app.include_router(panorama_router)
app.include_router(recipe_router)
app.include_router(interactive_story_router)
app.include_router(canvas_workflow_router)


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
    control = task.get("workflow_control") or {}
    if not task.get("task_id") or (task.get("status") != "running" and not control.get("active")):
        return False

    if isinstance(task.get("workflow_control"), dict):
        task["workflow_control"]["active"] = False
    if task.get("status") != "running":
        return True
    if control.get("pause_requested"):
        task["status"] = "stopped" if control.get("stop_requested") else "paused"
        return True

    progress = task.get("stage_progress")
    if isinstance(progress, dict) and progress.get("status") == "success":
        # A stage can finish while the historical task-level status remains
        # running. It is complete and merely waiting for the next stage.
        task["status"] = "idle"
        task["fail_reason"] = None
    else:
        task["status"] = "interrupted"
        task["fail_reason"] = "服务重启导致后台任务中断，可点击恢复(/resume)从断点续跑"
        _record_stage_interruption(task)
    return True


def _record_stage_interruption(task: dict) -> None:
    """Close the dead stage run and tell the chat why the workflow stopped."""
    progress = task.get("stage_progress")
    if not isinstance(progress, dict) or progress.get("status") != "running":
        return
    from app.core.workflow_guide import append_stage_guidance
    from app.service.drama_service import DramaService

    progress["status"] = "error"
    progress["error"] = task["fail_reason"]
    progress["label"] = "服务重启，阶段执行中断"
    for call in progress.get("calls") or []:
        if isinstance(call, dict) and call.get("status") == "running":
            call["status"] = "error"
    append_stage_guidance(task, "interrupted", DramaService.STAGE_LABELS)


_usage_drain_task = None
_billing_upkeep_task = None
_payment_upkeep_task = None
_reconciliation_task = None
_account_watcher = None


async def _billing_upkeep(book: BillingBook | None) -> None:
    """Lots past their date, and holds left by a process that died."""
    while True:
        await asyncio.sleep(600)
        try:
            await get_platform_store().expire_points()
            await get_platform_store().send_membership_reminders()
            if book is not None:
                await asyncio.to_thread(book.release_stale)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - the next pass tries again
            logging.getLogger("main").warning("积分到期处理失败: %s", type(exc).__name__)


@app.on_event("startup")
async def _start_usage_billing():
    """Keep every provider call for billing. Balances are only touched while BILLING_ENFORCE is on."""
    global _usage_drain_task, _billing_upkeep_task, _payment_upkeep_task, _reconciliation_task, _account_watcher
    spool = usage_billing.UsageSpool()
    usage_ledger.configure_billing_sink(spool.append)
    _usage_drain_task = asyncio.create_task(usage_billing.run_drain_loop(get_platform_store(), spool, _task_owner))
    book = None
    if settings.billing_enforced():
        if not settings.payment_sandbox_enabled():
            await get_platform_store().void_sandbox_points()
        book = BillingBook(settings.database_url(), _task_owner)
        set_active_book(book)
        usage_ledger.configure_billing_guard(book)
        set_account_watcher(book)
    else:
        # Nothing is charged, but a closed account still must not reach a provider.
        _account_watcher = BillingBook(settings.database_url(), _task_owner)
        usage_ledger.configure_billing_guard(AccountGuard(_account_watcher))
        set_account_watcher(_account_watcher)
    _billing_upkeep_task = asyncio.create_task(_billing_upkeep(book))
    _payment_upkeep_task = asyncio.create_task(payment_flow.run_upkeep_loop(get_platform_store()))
    _reconciliation_task = asyncio.create_task(reconciliation.run_loop(get_platform_store(), read_usage_records))


@app.on_event("shutdown")
async def _stop_usage_billing():
    global _usage_drain_task, _billing_upkeep_task, _payment_upkeep_task, _reconciliation_task, _account_watcher
    usage_ledger.configure_billing_sink(None)
    usage_ledger.configure_billing_guard(None)
    set_account_watcher(None)
    if _account_watcher is not None:
        _account_watcher.close()
        _account_watcher = None
    book = active_book()
    set_active_book(None)
    if book is not None:
        book.close()
    if _billing_upkeep_task is not None:
        _billing_upkeep_task.cancel()
        _billing_upkeep_task = None
    if _payment_upkeep_task is not None:
        _payment_upkeep_task.cancel()
        _payment_upkeep_task = None
    if _reconciliation_task is not None:
        _reconciliation_task.cancel()
        _reconciliation_task = None
    if _usage_drain_task is None:
        return
    _usage_drain_task.cancel()
    _usage_drain_task = None
    try:
        await usage_billing.drain(get_platform_store(), usage_billing.UsageSpool(), _task_owner)
    except Exception as exc:  # noqa: BLE001 - the file stays and the next start loads it
        import logging
        logging.getLogger("main").warning("退出时用量入库失败，下次启动再试: %s", type(exc).__name__)


def _task_owner(task_id: str) -> str | None:
    task = usage_task_repository.get_task(task_id)
    return str(task.get("owner_user_id") or "") or None if isinstance(task, dict) else None


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
            if isinstance(t, dict) and (t.get("status") == "running" or (t.get("workflow_control") or {}).get("active")):
                if repo.mutate_task(t["task_id"], _recover_orphan_task_state):
                    n += 1
        if n:
            log.warning(f"[启动恢复] 已规范化 {n} 个残留 running 任务的状态")
    except Exception as e:
        log.error(f"[启动恢复] 孤儿任务回收失败: {str(e)[:160]}")
    # Video jobs the providers accepted before the restart keep running and are paid for:
    # poll them to their end in the background and record their clips; never re-submit.
    import threading
    from app.api.drama_api import service as drama_service

    def _resume():
        try:
            queues = drama_service.reconcile_generation_queues()
            if queues.get("requeued"):
                log.warning("[启动恢复] 生成队列: %s 项回到排队", queues["requeued"])
        except Exception as error:  # noqa: BLE001 - recovery must never take the server down
            log.error("[启动恢复] 生成队列整理失败: %s", str(error)[:160])
        try:
            outcome = drama_service.resume_interrupted_video_jobs()
            if any(outcome.values()):
                log.warning("[启动恢复] 视频任务续查: 取回 %s 条, 失败 %s 条", outcome["downloaded"], outcome["failed"])
        except Exception as error:  # noqa: BLE001 - recovery must never take the server down
            log.error("[启动恢复] 视频任务续查失败: %s", str(error)[:160])

    threading.Thread(target=_resume, name="video-job-resume", daemon=True).start()


@app.on_event("startup")
def _start_acquisition_sweep():
    """宣发获客的定时拉取：每隔 ACQUISITION_SYNC_MINUTES（默认 60，0 关闭）用官方接口读新评论并判定线索。

    只读不发：回复和私信始终由人点发送。没有配置 YOUTUBE_API_KEY 时整轮跳过，不花模型调用。
    """
    import logging
    import os
    import threading

    log = logging.getLogger("main")
    try:
        minutes = float(os.getenv("ACQUISITION_SYNC_MINUTES", "60"))
    except ValueError:
        minutes = 60.0
    if minutes <= 0:
        return
    stop = threading.Event()

    def _loop():
        from app.api.drama_api import acquisition
        from app.service.acquisition_service import KEY

        delay = 120.0  # 启动后先等两分钟，避开开发模式下的连续热重载。
        while not stop.wait(delay):
            delay = minutes * 60
            try:
                outcome = acquisition.scheduled_sweep(acquisition.repo.task_ids_containing(f'"{KEY}"'))
                if outcome["swept"] or outcome["failed"]:
                    log.info("[获客] 定时同步: %s 个项目, 失败 %s 个", outcome["swept"], outcome["failed"])
            except Exception as error:  # noqa: BLE001 - the sweep must never take the server down
                log.error("[获客] 定时同步失败: %s", str(error)[:160])

    threading.Thread(target=_loop, name="acquisition-sweep", daemon=True).start()


@app.get("/")
def read_root():
    return {
        "status": "online",
        "message": "AI Short Drama 8-Agent Backend Server is running successfully."
    }

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.server_host(),
        port=settings.server_port(),
        reload=settings.server_reload(),
    )
