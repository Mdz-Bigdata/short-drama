# -*- coding: utf-8 -*-
import os
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.api.drama_api import router as drama_router
from app.api.auth_api import router as auth_router
from app.core.media_compositor import MEDIA_DIR

app = FastAPI(
    title="AI短剧 8-Agent 工业化协同成片系统",
    description="支持一键成片与步骤式断点续传的 AI 短剧/漫剧生成管理后端",
    version="1.0.0"
)

# 允许跨域请求 CORS (由于需要带凭证Cookie，allow_origins不能使用"*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载本地生成媒体的静态访问路由 (TTS 配音、合成成片)
os.makedirs(MEDIA_DIR, exist_ok=True)
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")

# 挂载 API 路由
app.include_router(drama_router)
app.include_router(auth_router)

@app.on_event("startup")
def _recover_orphan_tasks():
    """
    服务启动时回收孤儿任务 (防孤儿)：一键成片走 FastAPI BackgroundTasks，
    若服务在生成途中重启/崩溃，任务会永久卡在 running。启动时把这些残留 running
    重置为 interrupted —— 前端可见且不再"假装在跑"，可通过 /resume 从断点续跑。
    """
    import logging
    log = logging.getLogger("main")
    try:
        from app.repository.task_repo import TaskRepository
        repo = TaskRepository()
        n = 0
        for t in repo.list_all_tasks():
            if isinstance(t, dict) and t.get("status") == "running" and t.get("task_id"):
                t["status"] = "interrupted"
                t["fail_reason"] = "服务重启导致后台任务中断，可点击恢复(/resume)从断点续跑"
                repo.save_task(t["task_id"], t)
                n += 1
        if n:
            log.warning(f"[启动恢复] 已回收 {n} 个中断的运行中任务 -> interrupted (可 /resume 续跑)")
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
