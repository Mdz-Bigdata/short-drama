from fastapi import APIRouter, HTTPException, BackgroundTasks, Form, File, UploadFile, Depends
from typing import List, Dict, Any, Optional
from app.schema.drama import DramaCreateRequest, DramaTaskResponse
from app.service.drama_service import DramaService
from app.repository.task_repo import TaskRepository
from app.api.auth_api import get_current_user, require_admin
from app.core.video_quality import VideoQualityMeasurements

# 创建 API 路由，全局挂载登录身份校验依赖
router = APIRouter(prefix="/api/drama", tags=["AI短剧制作"], dependencies=[Depends(get_current_user)])
service = DramaService()
repo = TaskRepository()

@router.post("/create", response_model=DramaTaskResponse)
def create_new_task(req: DramaCreateRequest):
    """
    新建一个 AI 短剧任务。
    如果是一键成片，则初始化后可直接一键生成。
    """
    try:
        task_data = service.create_task(req)
        return task_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"创建任务失败: {str(e)}")

@router.get("/list", response_model=List[DramaTaskResponse])
def get_all_tasks():
    """
    获取所有的短剧生成任务列表历史
    """
    return repo.list_all_tasks()

@router.get("/{task_id}/status", response_model=DramaTaskResponse)
def get_task_status(task_id: str):
    """
    获取单条任务的状态 (提供断点续传的中间结果)
    """
    task = service.get_task_status(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task

@router.post("/{task_id}/next", response_model=DramaTaskResponse)
async def run_next_stage(task_id: str, current_stage: int):
    """
    一步一步引导模式：启动执行指定步骤阶段
    """
    try:
        updated_task = await service.execute_stage(task_id, current_stage)
        return updated_task
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"执行第 {current_stage} 阶段出错: {str(e)}")

@router.post("/{task_id}/pause", response_model=DramaTaskResponse)
def pause_running_task(task_id: str):
    """
    暂停正在执行中的一键成片任务 (断点锁定)
    """
    task = service.pause_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task

@router.post("/{task_id}/resume", response_model=DramaTaskResponse)
def resume_paused_task(task_id: str, background_tasks: BackgroundTasks):
    """
    恢复被暂停的任务，并自动在后台线程中继续一键生成
    """
    task = service.resume_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    # 异步在后台恢复执行剩下的步骤
    background_tasks.add_task(service.execute_all_stages, task_id)
    return task

@router.post("/{task_id}/run_all", response_model=DramaTaskResponse)
def run_all_stages_one_click(task_id: str, background_tasks: BackgroundTasks):
    """
    一键成片模式：异步在后台连续串行运行 1 到 8 步骤
    """
    task = service.get_task_status(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    
    task["status"] = "running"
    repo.save_task(task_id, task)
    
    # 异步在后台执行全生命周期
    background_tasks.add_task(service.execute_all_stages, task_id)
    return task

@router.post("/{task_id}/episodes/plan")
def plan_episodes_route(task_id: str):
    """把已生成的完整剧本(阶段2)切分为多集，返回分集清单。需先完成阶段1-3。"""
    try:
        task = service.plan_episodes(task_id)
        return {"status": "success", "totalEpisodes": task.get("total_episodes", 0),
                "episodes": [{"index": e["index"], "title": e["title"], "status": e["status"]}
                             for e in task.get("episodes", [])]}
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"分集失败: {str(e)}")

@router.get("/{task_id}/episodes")
def list_episodes_route(task_id: str):
    """获取多集制作清单与各集状态、成片地址。"""
    task = service.get_task_status(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    eps = task.get("episodes", []) or []
    return {
        "totalEpisodes": task.get("total_episodes", len(eps)),
        "currentEpisode": task.get("current_episode", 0),
        "episodes": [{"index": e.get("index"), "title": e.get("title"), "status": e.get("status"),
                      "videoUrl": e.get("video_url"), "shotsCount": len(e.get("shots") or []),
                      "summary": e.get("summary", "")} for e in eps],
    }

@router.post("/{task_id}/episodes/{ep_index}/produce")
def produce_episode_route(task_id: str, ep_index: int, background_tasks: BackgroundTasks):
    """逐集制作：后台异步生成指定集 (分镜->尾帧链式逐镜生成->情绪配音->合成2.5-3min单集)。"""
    task = service.get_task_status(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if not task.get("episodes"):
        raise HTTPException(status_code=400, detail="请先调用 /episodes/plan 进行分集")
    ep = next((e for e in task["episodes"] if e.get("index") == ep_index), None)
    if not ep:
        raise HTTPException(status_code=404, detail=f"第{ep_index}集不存在")

    async def _run():
        try:
            await service.produce_episode(task_id, ep_index)
        except Exception as e:
            import logging
            logging.getLogger("app.api.drama_api").error(f"制作第{ep_index}集失败: {str(e)}")

    background_tasks.add_task(_run)
    ep["status"] = "running"
    repo.save_task(task_id, task)
    return {"status": "running", "episode": ep_index, "message": f"第{ep_index}集已开始后台制作，请轮询 /episodes 查看进度"}

@router.post("/{task_id}/chat", response_model=DramaTaskResponse)
async def chat_with_agent(task_id: str, payload: Dict[str, str]):
    """
    通过对话引导智能体进行短剧内容调整与创作
    """
    message = payload.get("message", "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="消息内容不能为空")
    try:
        updated_task = await service.chat_instruction(task_id, message)
        return updated_task
    except ValueError as ve:
        raise HTTPException(status_code=404, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"对话处理失败: {str(e)}")


@router.post("/{task_id}/quality/video", response_model=DramaTaskResponse)
def submit_video_quality(task_id: str, measurements: VideoQualityMeasurements):
    """提交真实多模态或人工复核证据；只有通过后任务才标记 completed。"""
    try:
        return service.submit_video_quality(task_id, measurements)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

@router.post("/{task_id}/update_config", response_model=DramaTaskResponse)
def update_task_config(task_id: str, req: DramaCreateRequest):
    """
    更新现有短剧任务的参数配置
    """
    try:
        task = service.update_task_config(task_id, req)
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        return task
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"更新配置失败: {str(e)}")

@router.post("/import_skill")
async def import_new_skill(
    import_type: str = Form(..., description="导入类型: github, clawhub, npx, zip"),
    url: Optional[str] = Form(None, description="GitHub或Clawhub链接"),
    package_name: Optional[str] = Form(None, description="NPX包名"),
    file: Optional[UploadFile] = File(None, description="上传的ZIP技能包文件"),
    _admin: dict = Depends(require_admin),
):
    """
    导入并添加外部自定义 Skill 技能包
    """
    try:
        result = await service.import_skill_logic(import_type, url, package_name, file)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"导入Skill失败: {str(e)}")

@router.get("/skills", response_model=List[Dict[str, Any]])
def get_imported_skills():
    """
    获取所有已导入的 Skill 技能列表
    """
    return service.get_all_skills()

@router.delete("/skills/{skill_name}")
def delete_imported_skill(skill_name: str, _admin: dict = Depends(require_admin)):
    """
    删除指定的已导入 Skill 技能包
    """
    try:
        result = service.delete_skill_logic(skill_name)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除Skill失败: {str(e)}")

@router.delete("/{task_id}")
def delete_drama_task(task_id: str):
    """
    物理删除指定的短剧生成任务
    """
    try:
        success = service.delete_task(task_id)
        if not success:
            raise HTTPException(status_code=404, detail="任务不存在")
        return {"status": "success", "message": f"任务 {task_id} 已成功删除"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除任务失败: {str(e)}")

@router.post("/seedance2_video")
async def seedance2_video_route(payload: Dict[str, Any]):
    """
    Seedance 2.0 多模态生视频统一接口，支持四种能力：
      - 文生视频：{"prompt": "..."}
      - 图生视频-首帧：{"prompt": "...", "first_frame": "<图片URL>"}
      - 图生视频-首尾帧：{"prompt": "...", "first_frame": "<首帧URL>", "last_frame": "<尾帧URL>"}
      - 多模态参考生视频：{"prompt": "...", "ref_images": ["url",...0-9], "ref_videos": [..0-3], "ref_audios": [..0-3]}
    可选 {"optimize": false} 关闭 sd2-pe 提示词优化器。
    """
    prompt = (payload.get("prompt") or "").strip()
    first_frame = payload.get("first_frame")
    last_frame = payload.get("last_frame")
    ref_images = payload.get("ref_images") or []
    ref_videos = payload.get("ref_videos") or []
    ref_audios = payload.get("ref_audios") or []
    optimize = payload.get("optimize", True)
    if not prompt and not first_frame and not ref_images and not ref_videos:
        raise HTTPException(status_code=400, detail="至少需要提供 prompt 或 first_frame 或参考素材之一")
    if ref_audios and not (ref_images or ref_videos or first_frame):
        raise HTTPException(status_code=400, detail="不可单独输入音频，应至少包含 1 个参考视频或图片")
    try:
        result = await service.generate_seedance2_video(
            prompt, first_frame=first_frame, last_frame=last_frame,
            ref_images=ref_images, ref_videos=ref_videos, ref_audios=ref_audios, optimize=optimize
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Seedance2.0 生视频失败: {str(e)}")

@router.post("/parse_script")
async def parse_script_file_route(file: UploadFile = File(..., description="上传的剧本文件")):
    """
    手动上传剧本文件解析接口，支持 .txt, .md, .docx, .pdf, .fdx。
    """
    try:
        maximum = 20 * 1024 * 1024
        file_bytes = await file.read(maximum + 1)
        if len(file_bytes) > maximum:
            raise ValueError("剧本文件不能超过 20MB")
        safe_name = file.filename or "script.txt"
        content = service.parse_script_file(safe_name, file_bytes)
        return {
            "status": "success",
            "filename": safe_name,
            "content": content
        }
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"解析剧本文件失败: {str(e)}")
