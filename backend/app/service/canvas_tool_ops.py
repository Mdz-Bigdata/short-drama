"""Doing what a canvas tool says: the disk, ffmpeg, PIL and the model calls behind ``app.core.canvas_tools``.

Everything a tool writes goes under the media folder the way any other canvas result does, so a
result stays reachable after the run. Temporary downloads are removed however the tool ends.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import os
import subprocess
import tempfile
import uuid
from collections.abc import Mapping
from typing import Any

from PIL import Image, ImageOps

from app.core import action_grammar, canvas_tools, media_compositor, panorama, studio_canvas, usage_ledger
from app.core.canvas_tools import CanvasTool, CanvasToolError

logger = logging.getLogger("app.service.canvas_tool_ops")

_FFMPEG_TIMEOUT_S = 600
_FFPROBE_TIMEOUT_S = 30
# Past this a local resize only makes a huge file: no provider takes it, and the machine's time goes on nothing.
_MAX_IMAGE_SIDE = 8192
_MAX_VIDEO_LONG_SIDE = 3840
_MAX_SHOTS_IN_SHEET = 16
_SHEET_COLUMNS = 4
_SHEET_CELL = (360, 360)
_DEFAULT_GIF_SECONDS = 6.0
_VISION_TOKENS = 1500
_BEAT_TOKENS = 3000
_WRITER_TOKENS = 6000


def _output_path(tag: str, tool: CanvasTool, extension: str) -> tuple[str, str]:
    os.makedirs(media_compositor.MEDIA_DIR, exist_ok=True)
    name = f"canvas_{tag}_{tool.id}_{uuid.uuid4().hex[:10]}.{extension}"
    return os.path.join(media_compositor.MEDIA_DIR, name), media_compositor.public_url(name)


def _materialize(url: str, suffix: str, scratch: str) -> str:
    """A path to read ``url`` from: the file itself under /media, otherwise a download into ``scratch``."""
    local = media_compositor.local_media_path(url)
    if local and os.path.exists(local):
        return local
    target = os.path.join(scratch, f"{uuid.uuid4().hex[:10]}{suffix}")
    if not media_compositor._download(url, target):
        raise RuntimeError("上游的文件取不到了，可能已经过期")
    return target


def _ffmpeg_bin() -> str:
    binary = media_compositor._ffmpeg()
    if not binary:
        raise CanvasToolError("服务器上没有 ffmpeg，这个工具无法运行")
    return binary


def _run_ffmpeg(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        done = subprocess.run([_ffmpeg_bin(), "-hide_banner", "-y", *arguments], capture_output=True, text=True, timeout=_FFMPEG_TIMEOUT_S, check=False)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("处理超时：视频太长或太大") from error
    if done.returncode != 0:
        logger.warning("[CanvasTool] ffmpeg 失败：%s", done.stderr[-500:])
        raise RuntimeError("ffmpeg 处理失败，这个文件可能已损坏或格式不支持")
    return done


def _probe(path: str) -> dict[str, Any]:
    probe = _ffmpeg_bin().replace("ffmpeg", "ffprobe")
    try:
        done = subprocess.run(
            [probe, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", path],
            capture_output=True, text=True, timeout=_FFPROBE_TIMEOUT_S, check=False,
        )
        data = json.loads(done.stdout or "{}")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as error:
        raise RuntimeError("读不出这段视频的信息") from error
    streams = data.get("streams") or []
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    if video is None:
        raise CanvasToolError("这个文件里没有视频画面")
    try:
        duration = float((data.get("format") or {}).get("duration") or video.get("duration") or 0)
    except (TypeError, ValueError):
        duration = 0.0
    return {
        "width": int(video.get("width") or 0), "height": int(video.get("height") or 0), "duration": duration,
        "has_audio": any(item.get("codec_type") == "audio" for item in streams),
    }


def _image_bytes_uri(path: str, drama: Any) -> str:
    with open(path, "rb") as handle:
        content = handle.read()
    return drama._reference_image_uri(content, mimetypes.guess_type(path)[0] or "image/png")


def _ask_vision(drama: Any, model: str, system: str, prompt: str, image_uri: str, task_id: str) -> tuple[str, str]:
    with usage_ledger.bind_task(task_id, "canvas_tool"):
        answer, used = drama.gateway.describe_image(model, system, prompt, image_uri, max_tokens=_VISION_TOKENS)
    if not used:
        raise CanvasToolError("没有可看图的文本模型：请在模型配置里启用一个标为「多模态」的文本模型")
    if not answer:
        raise RuntimeError(f"模型 {used} 没有返回结果（可能不支持图片输入或请求失败）")
    return str(answer).strip(), used


# ---------------------------------------------------------------------------- pictures
def upscale_image(path: str, factor: int, out: str) -> None:
    """Lanczos and a light unsharp: bigger and crisper, with no detail that was not there."""
    from PIL import ImageFilter

    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    size = (image.width * factor, image.height * factor)
    if max(size) > _MAX_IMAGE_SIDE:
        raise CanvasToolError(f"放大后最长边会超过 {_MAX_IMAGE_SIDE} 像素，请换小一点的倍数")
    image.resize(size, Image.Resampling.LANCZOS).filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=2)).save(out, "PNG")


def cut_cell(path: str, rows: int, columns: int, index: int, out: str) -> None:
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    image.crop(canvas_tools.grid_box(image.width, image.height, rows, columns, index)).save(out, "PNG")


def composite(paths: list[str], out: str) -> None:
    """The cast of the desk still pasted onto a generated picture, through the mask: a control frame put back together.

    The mask is found by what it is (black and white), so the other two may come in either order: a picture
    the model made and the still the mask was cut from. The one that is not the still is the base.
    """
    opened = [ImageOps.exif_transpose(Image.open(path)).convert("RGB") for path in paths]
    masks = [index for index, image in enumerate(opened) if canvas_tools.looks_like_mask(image.convert("L").histogram())]
    if len(masks) != 1:
        raise CanvasToolError("要连三张图：生成好的新图、导演台的完整画面截图，和它的人物遮罩（黑底白人）；现在认不出哪张是遮罩" if not masks else "连了不止一张遮罩")
    mask = opened[masks[0]].convert("L")
    others = [image for index, image in enumerate(opened) if index != masks[0]]
    # The still was captured with the mask, so it is the one whose size the mask has; the other is the base.
    same = [index for index, image in enumerate(others) if image.size == mask.size]
    still_index = same[0] if same else 1
    still, base = others[still_index], others[1 - still_index]
    still = still.resize(base.size, Image.Resampling.LANCZOS)
    mask = mask.resize(base.size, Image.Resampling.LANCZOS)
    Image.composite(still, base, mask).save(out, "PNG")


def pad_for_outpaint(path: str, ratio: float, out: str) -> None:
    """The picture centred on a canvas of the target shape; what is left to fill is plain mid grey, which reads as blank to a model."""
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    current = image.width / image.height
    if abs(current - ratio) < 0.01:
        raise CanvasToolError("这张图已经是这个画幅了，换一个再扩")
    width = image.width if current > ratio else round(image.height * ratio)
    height = round(image.width / ratio) if current > ratio else image.height
    canvas = Image.new("RGB", (width, height), (128, 128, 128))
    canvas.paste(image, ((width - image.width) // 2, (height - image.height) // 2))
    canvas.save(out, "PNG")


# ---------------------------------------------------------------------------- video
def upscale_video(path: str, factor: float, out: str) -> None:
    facts = _probe(path)
    width, height = round(facts["width"] * factor / 2) * 2, round(facts["height"] * factor / 2) * 2
    if max(width, height) > _MAX_VIDEO_LONG_SIDE:
        raise CanvasToolError(f"放大后最长边会超过 {_MAX_VIDEO_LONG_SIDE} 像素，请换小一点的倍数")
    _run_ffmpeg(["-i", path, "-vf", f"scale={width}:{height}:flags=lanczos,unsharp=5:5:0.6", "-c:v", "libx264", "-crf", "18", "-preset", "medium",
                 "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", out])


def erase_region(path: str, params: Mapping[str, Any], out: str) -> None:
    facts = _probe(path)
    x, y, width, height = canvas_tools.erase_box(params, facts["width"], facts["height"])
    _run_ffmpeg(["-i", path, "-vf", f"delogo=x={x}:y={y}:w={width}:h={height}", "-c:v", "libx264", "-crf", "18", "-preset", "medium",
                 "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", out])


def extract_audio(path: str, out: str) -> None:
    if not _probe(path)["has_audio"]:
        raise CanvasToolError("这段视频没有声音")
    _run_ffmpeg(["-i", path, "-vn", "-c:a", "libmp3lame", "-q:a", "2", out])


def extract_frame(path: str, params: Mapping[str, Any], out: str) -> None:
    facts = _probe(path)
    where = str(params.get("at") or "first")
    if where == "last":
        # Seeking to the very end can land past the last frame and write nothing, so read the last second and keep the final frame.
        _run_ffmpeg(["-sseof", "-1", "-i", path, "-update", "1", out])
    else:
        at = 0.0 if where != "time" else canvas_tools.number(params, "seconds", 0, 0, 3600)
        if at > facts["duration"]:
            raise CanvasToolError(f"这段视频只有 {facts['duration']:.1f} 秒")
        _run_ffmpeg(["-ss", f"{at:.3f}", "-i", path, "-frames:v", "1", out])
    if not os.path.exists(out):
        raise RuntimeError("没能从这个位置取到画面，请换一个时间")


def to_gif(path: str, params: Mapping[str, Any], out: str) -> None:
    fps = int(canvas_tools.number(params, "fps", 12, 4, 24))
    width = int(canvas_tools.number(params, "width", 480, 120, 960))
    seconds = canvas_tools.number(params, "seconds", _DEFAULT_GIF_SECONDS, 0.5, 30)
    graph = f"fps={fps},scale={width}:-2:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer"
    _run_ffmpeg(["-t", f"{seconds:.2f}", "-i", path, "-filter_complex", graph, "-loop", "0", out])


def detect_cuts(path: str, duration: float, sensitivity: float = 0.35) -> list[float]:
    done = _run_ffmpeg(["-i", path, "-vf", f"select='gt(scene,{sensitivity})',showinfo", "-an", "-f", "null", "-"])
    return canvas_tools.scene_cuts(done.stderr.splitlines(), duration)


def contact_sheet(path: str, starts: list[float], out: str, scratch: str) -> None:
    """One frame from each shot, in order: what a vision model can look at in one image."""
    rows = (len(starts) + _SHEET_COLUMNS - 1) // _SHEET_COLUMNS
    sheet = Image.new("RGB", (_SHEET_COLUMNS * _SHEET_CELL[0], rows * _SHEET_CELL[1]), (24, 24, 24))
    for index, start in enumerate(starts):
        frame = os.path.join(scratch, f"frame_{index}.jpg")
        _run_ffmpeg(["-ss", f"{start:.3f}", "-i", path, "-frames:v", "1", "-q:v", "4", frame])
        with Image.open(frame) as image:
            cell = ImageOps.contain(image.convert("RGB"), _SHEET_CELL)
        row, column = divmod(index, _SHEET_COLUMNS)
        sheet.paste(cell, (column * _SHEET_CELL[0], row * _SHEET_CELL[1]))
    sheet.save(out, "JPEG", quality=85)


# ---------------------------------------------------------------------------- one run
def run_tool(
    tool: CanvasTool, *, inputs: studio_canvas.Inputs, params: Mapping[str, Any], prompt: str, model: str, tag: str, task: Mapping[str, Any], drama: Any,
) -> dict[str, Any]:
    """Run ``tool`` and answer with what its output holds: ``{"url": …}`` or, for a text result, ``{"text": …}``."""
    with tempfile.TemporaryDirectory(prefix="canvas_tool_") as scratch:
        if tool.engine == "image":
            return _run_image(tool, inputs, params, prompt, model, tag, task, drama, scratch)
        if tool.engine != "local":
            return _run_model(tool, inputs, params, prompt, model, tag, task, drama, scratch)
        return _run_local(tool, inputs, params, tag, scratch)


def _pictures(inputs: studio_canvas.Inputs) -> list[str]:
    return [*([inputs.first_frame] if inputs.first_frame else []), *inputs.ref_images]


def _run_image(
    tool: CanvasTool, inputs: studio_canvas.Inputs, params: Mapping[str, Any], prompt: str, model: str, tag: str, task: Mapping[str, Any], drama: Any, scratch: str,
) -> dict[str, Any]:
    references = _pictures(inputs)
    size = None
    padded = None
    if tool.id == "scene_360":
        scene_prompt = panorama.panorama_prompt(prompt, has_reference=bool(references))
        size = panorama.PANORAMA_SIZE
    else:
        scene_prompt = canvas_tools.image_prompt(tool, params, prompt)
    if tool.id == "outpaint":
        padded, url = _output_path(tag, tool, "png")
        pad_for_outpaint(_materialize(references[0], ".png", scratch), canvas_tools.OUTPAINT_RATIOS[canvas_tools.outpaint_ratio(params)], padded)
        references = [url, *references[1:]]
    try:
        generated, _ = drama.gateway.generate_image(
            model, scene_prompt, ref_images=references or None, size=size, enhance_prompt=False, require_reference_support=bool(references),
        )
    finally:
        # The padded picture only had to last as long as the model call.
        if padded and os.path.exists(padded):
            os.remove(padded)
    if not generated:
        raise RuntimeError("图像模型没有返回结果")
    if tool.id != "scene_360":
        return {"url": generated}
    # A model does not promise 2:1 or edges that meet, and this picture is going to be wrapped round a sphere.
    from app.service.panorama_service import _bytes_of

    fitted = panorama.fit_panorama(_bytes_of(generated))
    out, url = _output_path(tag, tool, "jpg")
    with open(out, "wb") as handle:
        handle.write(fitted.content)
    return {"url": url}


def _run_model(
    tool: CanvasTool, inputs: studio_canvas.Inputs, params: Mapping[str, Any], prompt: str, model: str, tag: str, task: Mapping[str, Any], drama: Any, scratch: str,
) -> dict[str, Any]:
    task_id = str(task.get("task_id") or "")
    if tool.id == "beat_plan":
        with usage_ledger.bind_task(task_id, "canvas_tool"):
            answer = drama.gateway.call_llm(model, canvas_tools.BEAT_SYSTEM, canvas_tools.beat_prompt(prompt), "", max_tokens=_BEAT_TOKENS)
        beats = canvas_tools.parse_beats(answer)
        return {"text": canvas_tools.beats_text(beats), "beats": beats}
    if tool.id in _WRITERS:
        return _write(tool, prompt, model, tag, task_id, drama)
    if tool.id == "voice_isolate":
        return _isolate_voice(tool, inputs, tag, scratch)
    if tool.id == "shot_analysis":
        return _analyze_shots(tool, inputs, model, task_id, drama, scratch)
    picture = _image_bytes_uri(_materialize(_pictures(inputs)[0], ".png", scratch), drama)
    system, question = {
        "reverse_prompt": (canvas_tools.REVERSE_SYSTEM, canvas_tools.REVERSE_PROMPT),
        "mark_detect": (canvas_tools.MARK_SYSTEM, canvas_tools.MARK_PROMPT),
        "frame_review": (canvas_tools.REVIEW_SYSTEM, canvas_tools.REVIEW_PROMPT.format(extra=f"这一镜应该是：{prompt}。" if prompt else "")),
    }[tool.id]
    answer, used = _ask_vision(drama, model, system, question, picture, task_id)
    return {"text": answer, "model": used}


_WRITERS = {
    "action_breakdown": (action_grammar.BREAKDOWN_SYSTEM, "{story}"),
    "link_design": (canvas_tools.LINK_SYSTEM, canvas_tools.LINK_PROMPT),
    "frame_bridge": (canvas_tools.FRAME_BRIDGE_SYSTEM, canvas_tools.FRAME_BRIDGE_PROMPT),
    "script_write": (canvas_tools.SCRIPT_SYSTEM, canvas_tools.SCRIPT_PROMPT),
    "shot_table": (canvas_tools.SHOT_TABLE_SYSTEM, canvas_tools.SHOT_TABLE_PROMPT),
    "svg_art": (canvas_tools.SVG_SYSTEM, canvas_tools.SVG_PROMPT),
    "html_page": (canvas_tools.HTML_SYSTEM, canvas_tools.HTML_PROMPT),
}


def _write(tool: CanvasTool, prompt: str, model: str, tag: str, task_id: str, drama: Any) -> dict[str, Any]:
    story = " ".join(str(prompt or "").split()) if tool.id != "shot_table" else str(prompt or "").strip()
    if not story:
        raise CanvasToolError("连一段文本或写一下要做什么")
    system, template = _WRITERS[tool.id]
    question = action_grammar.breakdown_prompt(story) if tool.id == "action_breakdown" else template.format(story=story)
    with usage_ledger.bind_task(task_id, "canvas_tool"):
        answer = drama.gateway.call_llm(model, system, question, "", max_tokens=_WRITER_TOKENS)
    if not answer:
        raise RuntimeError("文本模型没有返回结果")
    if tool.id == "action_breakdown":
        try:
            return {"text": action_grammar.parse_breakdown(answer)}
        except ValueError as error:
            raise CanvasToolError(str(error)) from error
    if tool.id in {"script_write", "link_design", "frame_bridge"}:
        return {"text": str(answer).strip()}
    if tool.id == "shot_table":
        shots = canvas_tools.parse_shots(answer)
        return {"text": canvas_tools.shots_text(shots), "beats": canvas_tools.shots_as_beats(shots)}
    if tool.id == "html_page":
        return {"text": canvas_tools.clean_html(answer), "html": True}
    out, url = _output_path(tag, tool, "svg")
    with open(out, "w", encoding="utf-8") as handle:
        handle.write(canvas_tools.clean_svg(answer))
    return {"url": url}


def _isolate_voice(tool: CanvasTool, inputs: studio_canvas.Inputs, tag: str, scratch: str) -> dict[str, Any]:
    from app.core.providers.elevenlabs import ElevenLabsClient

    track = os.path.join(scratch, "track.mp3")
    extract_audio(_materialize(inputs.ref_videos[0], ".mp4", scratch), track)
    out, url = _output_path(tag, tool, "mp3")
    with open(track, "rb") as handle:
        isolated = ElevenLabsClient().isolate_audio(handle, filename="track.mp3")
    with open(out, "wb") as handle:
        handle.write(isolated)
    return {"url": url}


def _analyze_shots(tool: CanvasTool, inputs: studio_canvas.Inputs, model: str, task_id: str, drama: Any, scratch: str) -> dict[str, Any]:
    path = _materialize(inputs.ref_videos[0], ".mp4", scratch)
    duration = _probe(path)["duration"]
    cuts = detect_cuts(path, duration)
    starts = [0.0, *cuts]
    spans = [f"{start:.2f}-{(starts[index + 1] if index + 1 < len(starts) else duration):.2f}s" for index, start in enumerate(starts)]
    # A frame just inside each shot: exactly on a cut can still be the outgoing shot.
    sampled = [start + 0.1 for start in starts[:_MAX_SHOTS_IN_SHEET]]
    sheet = os.path.join(scratch, "sheet.jpg")
    contact_sheet(path, sampled, sheet, scratch)
    question = canvas_tools.SHOT_PROMPT.format(count=len(sampled), cuts="、".join(spans[:_MAX_SHOTS_IN_SHEET]))
    answer, used = _ask_vision(drama, model, canvas_tools.SHOT_SYSTEM, question, _image_bytes_uri(sheet, drama), task_id)
    note = f"（共 {len(starts)} 个镜头，这里只看了前 {_MAX_SHOTS_IN_SHEET} 个）\n" if len(starts) > _MAX_SHOTS_IN_SHEET else ""
    return {"text": note + answer, "cuts": cuts, "model": used}


def _run_local(tool: CanvasTool, inputs: studio_canvas.Inputs, params: Mapping[str, Any], tag: str, scratch: str) -> dict[str, Any]:
    if tool.id == "upscale_image":
        out, url = _output_path(tag, tool, "png")
        upscale_image(_materialize(_pictures(inputs)[0], ".png", scratch), int(canvas_tools.number(params, "factor", 2, 2, 4)), out)
    elif tool.id == "grid_cell":
        out, url = _output_path(tag, tool, "png")
        rows, columns = int(canvas_tools.number(params, "rows", 3, 1, 12)), int(canvas_tools.number(params, "columns", 3, 1, 12))
        cut_cell(_materialize(_pictures(inputs)[0], ".png", scratch), rows, columns, int(canvas_tools.number(params, "cell", 1, 1, 144)) - 1, out)
    elif tool.id == "composite":
        out, url = _output_path(tag, tool, "png")
        composite([_materialize(picture, ".png", scratch) for picture in _pictures(inputs)[:3]], out)
    elif tool.id == "video_upscale":
        out, url = _output_path(tag, tool, "mp4")
        upscale_video(_materialize(inputs.ref_videos[0], ".mp4", scratch), canvas_tools.number(params, "factor", 2, 1.1, 4), out)
    elif tool.id == "video_erase":
        out, url = _output_path(tag, tool, "mp4")
        erase_region(_materialize(inputs.ref_videos[0], ".mp4", scratch), params, out)
    elif tool.id == "audio_extract":
        out, url = _output_path(tag, tool, "mp3")
        extract_audio(_materialize(inputs.ref_videos[0], ".mp4", scratch), out)
    elif tool.id == "frame_extract":
        out, url = _output_path(tag, tool, "png")
        extract_frame(_materialize(inputs.ref_videos[0], ".mp4", scratch), params, out)
    elif tool.id == "to_gif":
        out, url = _output_path(tag, tool, "gif")
        to_gif(_materialize(inputs.ref_videos[0], ".mp4", scratch), params, out)
    else:
        raise CanvasToolError(f"{tool.label} 不是本地工具")
    return {"url": url}


__all__ = ["run_tool"]
