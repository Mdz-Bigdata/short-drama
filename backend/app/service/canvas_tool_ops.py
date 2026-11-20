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
from app.core import move_sheets, sprite_frames
from app.core.canvas_tools import CanvasTool, CanvasToolError
from app.core import prompt_data


_WORDING_FILE = "canvas_tool_ops"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/canvas_tool_ops.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)

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
        raise RuntimeError(_text_of("_materialize.text"))
    return target


def _ffmpeg_bin() -> str:
    binary = media_compositor._ffmpeg()
    if not binary:
        raise CanvasToolError(_text_of("_ffmpeg_bin.text"))
    return binary


def _run_ffmpeg(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        done = subprocess.run([_ffmpeg_bin(), "-hide_banner", "-y", *arguments], capture_output=True, text=True, timeout=_FFMPEG_TIMEOUT_S, check=False)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(_text_of("_run_ffmpeg.text")) from error
    if done.returncode != 0:
        logger.warning("[CanvasTool] ffmpeg 失败：%s", done.stderr[-500:])
        raise RuntimeError(_text_of("_run_ffmpeg.text.2"))
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
        raise RuntimeError(_text_of("_probe.text")) from error
    streams = data.get("streams") or []
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    if video is None:
        raise CanvasToolError(_text_of("_probe.text.2"))
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
        raise CanvasToolError(_text_of("_ask_vision.text"))
    if not answer:
        raise RuntimeError(_text_of("_ask_vision.text.2").format(used))
    return str(answer).strip(), used


# ---------------------------------------------------------------------------- pictures
def upscale_image(path: str, factor: int, out: str) -> None:
    """Lanczos and a light unsharp: bigger and crisper, with no detail that was not there."""
    from PIL import ImageFilter

    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    size = (image.width * factor, image.height * factor)
    if max(size) > _MAX_IMAGE_SIDE:
        raise CanvasToolError(_text_of("upscale_image.text").format(_MAX_IMAGE_SIDE))
    image.resize(size, Image.Resampling.LANCZOS).filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=2)).save(out, "PNG")


def cut_cell(path: str, rows: int, columns: int, index: int, out: str) -> None:
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    image.crop(canvas_tools.grid_box(image.width, image.height, rows, columns, index)).save(out, "PNG")


CARD_SIZE = (1600, 400)
#: Two colours closer than this are one block of the card. A still with little colour in it is asked again with
#: a finer eye, so the card still has its six blocks.
CARD_SAME_COLOUR = (18.0, 10.0, 5.0, 0.0)
CARD_MIN_BLOCKS = 6
#: A still is first broken into this many colours; the card picks among them.
CARD_CLUSTERS = 24
#: An accent or a highlight has to cover at least this share of the picture to earn a block.
CARD_VISIBLE_SHARE = 0.004
#: How far against the picture's own lean a pixel has to sit (0–255 scale) to count as accent.
CARD_ACCENT_LEAN = 12.0
#: A thumbnail this small is enough to tell flat blocks from a photograph.
_CARD_PROBE = (96, 12)


def _small(path: str, side: int) -> Image.Image:
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
    image.thumbnail((side, side))
    return image


def _palette(path: str, count: int) -> list[tuple[int, int, int]]:
    """The ``count`` colours that cover most of a picture, the most used first."""
    reduced = _small(path, 256).quantize(colors=count, method=Image.Quantize.MEDIANCUT)
    palette = reduced.getpalette() or []
    used = sorted(reduced.getcolors() or [], reverse=True)
    return [(palette[index * 3], palette[index * 3 + 1], palette[index * 3 + 2]) for _, index in used if index * 3 + 2 < len(palette)]


def _luminance(colour: tuple[float, float, float]) -> float:
    return 0.2126 * colour[0] + 0.7152 * colour[1] + 0.0722 * colour[2]


def _chroma(colour: tuple[float, float, float]) -> tuple[float, float, float]:
    """A colour with its grey taken out: which way it leans, and how far."""
    grey = sum(colour) / 3
    return (colour[0] - grey, colour[1] - grey, colour[2] - grey)


def _mean(pixels: list[tuple[int, int, int]]) -> tuple[int, int, int]:
    return (round(sum(p[0] for p in pixels) / len(pixels)), round(sum(p[1] for p in pixels) / len(pixels)), round(sum(p[2] for p in pixels) / len(pixels)))


def _accent_and_highlight(path: str) -> list[tuple[int, int, int]]:
    """What a count by area misses, read off the pixels themselves: the accent, then the highlight.

    The accent is the patch that leans against the picture as a whole (a warm lantern in a cold street);
    the highlight is its brightest patch. Each has to cover a visible share of the frame, and a picture with
    no lean of its own has no accent.
    """
    pixels = list(_small(path, 128).getdata())
    if not pixels:
        return []
    enough = max(1, round(len(pixels) * CARD_VISIBLE_SHARE))
    found: list[tuple[int, int, int]] = []
    overall = _chroma(tuple(sum(pixel[channel] for pixel in pixels) / len(pixels) for channel in range(3)))
    lean = sum(value ** 2 for value in overall) ** 0.5
    if lean >= 3:
        against = sorted(((-sum(a * b for a, b in zip(_chroma(pixel), overall)) / lean, pixel) for pixel in pixels), reverse=True)
        # Judged at the edge of a visible patch, not at the single strongest pixel: one stray spark is not an accent.
        edge = against[enough - 1][0]
        if edge >= CARD_ACCENT_LEAN:
            found.append(_mean([pixel for score, pixel in against if score >= edge * 0.8][:max(enough, len(pixels) // 20)]))
    brightest = sorted(pixels, key=_luminance, reverse=True)[:enough]
    found.append(_mean(brightest))
    return found


def _apart(colour: tuple[int, int, int], others: list[tuple[int, int, int]], distance: float) -> bool:
    return colour not in others and all(sum((a - b) ** 2 for a, b in zip(colour, other)) ** 0.5 >= distance for other in others)


def card_colours(paths: list[str], count: int) -> list[tuple[int, int, int]]:
    """A still's palette as the card shows it: shadow to highlight, near-twins folded into one.

    Most blocks go to what covers the most of the picture. Two are kept for what a count by area would
    miss: the accent (a warm lantern in a cold street) and the brightest highlight. A second picture is a
    palette strip somebody brought along: its colours go in first, so the card stays ``count`` blocks at most.
    """
    brought = _palette(paths[1], 4) if len(paths) > 1 else []
    special = _accent_and_highlight(paths[0])
    found = _palette(paths[0], CARD_CLUSTERS)
    picked: list[tuple[int, int, int]] = []
    for apart in CARD_SAME_COLOUR:
        picked = []
        # Brought colours, the accent and the highlight first, so the big areas cannot crowd them off the card.
        for colour in [*brought, *special, *found]:
            if len(picked) >= count:
                break
            if _apart(colour, picked, apart):
                picked.append(colour)
        if len(picked) >= min(CARD_MIN_BLOCKS, count):
            break
    return sorted(picked[:count], key=_luminance)


def color_card(paths: list[str], count: int, out: str) -> None:
    """Equal, flat blocks of the still's own colours, darkest on the left: no words, no gradients, nothing else."""
    colours = card_colours(paths, count)
    if not colours:
        raise CanvasToolError(_text_of("color_card.text"))
    width, height = CARD_SIZE
    card = Image.new("RGB", CARD_SIZE)
    step = width // len(colours)
    for index, colour in enumerate(colours):
        right = width if index == len(colours) - 1 else (index + 1) * step
        card.paste(colour, (index * step, 0, right, height))
    card.save(out, format="PNG")


def is_color_card(path: str) -> bool:
    """Whether a picture is a strip of flat colour blocks (a card), told by what it is and not by where it was wired."""
    try:
        with Image.open(path) as source:
            # Nearest, so the edge between two blocks stays one step and a photograph keeps its noise.
            probe = ImageOps.exif_transpose(source).convert("RGB").resize(_CARD_PROBE, Image.Resampling.NEAREST)
    except OSError:
        return False
    width, height = probe.size
    pixels = probe.load()
    flat = 0
    for x in range(width):
        column = [pixels[x, y] for y in range(height)]
        if all(max(pixel[channel] for pixel in column) - min(pixel[channel] for pixel in column) <= 6 for channel in range(3)):
            flat += 1
    if flat < width * 0.95:
        return False
    # Blocks, not a sideways gradient and not one flat frame: along the strip the colour holds and then steps, and
    # nearly all of the change is in those steps.
    middle = [pixels[x, height // 2] for x in range(width)]
    steps = [max(abs(middle[x][channel] - middle[x - 1][channel]) for channel in range(3)) for x in range(1, width)]
    jumps = [step for step in steps if step >= 8]
    return bool(jumps) and sum(jumps) >= 0.8 * sum(steps)


def mood_references(pictures: list[str], scratch: str) -> list[str]:
    """The three pictures of a mood frame in the order its prompt names them: space base, original still, colour card.

    The card is recognised wherever it was connected and goes last; the other two keep the order they came in.
    """
    cards = [picture for picture in pictures if is_color_card(_materialize(picture, ".png", scratch))]
    if len(cards) != 1:
        return pictures
    return [*(picture for picture in pictures if picture != cards[0]), cards[0]]


def composite(paths: list[str], out: str) -> None:
    """The cast of the desk still pasted onto a generated picture, through the mask: a control frame put back together.

    The mask is found by what it is (black and white), so the other two may come in either order: a picture
    the model made and the still the mask was cut from. The one that is not the still is the base.
    """
    opened = [ImageOps.exif_transpose(Image.open(path)).convert("RGB") for path in paths]
    masks = [index for index, image in enumerate(opened) if canvas_tools.looks_like_mask(image.convert("L").histogram())]
    if len(masks) != 1:
        raise CanvasToolError(_text_of("composite.text") if not masks else _text_of("composite.text.2"))
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
        raise CanvasToolError(_text_of("pad_for_outpaint.text"))
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
        raise CanvasToolError(_text_of("upscale_video.text").format(_MAX_VIDEO_LONG_SIDE))
    _run_ffmpeg(["-i", path, "-vf", f"scale={width}:{height}:flags=lanczos,unsharp=5:5:0.6", "-c:v", "libx264", "-crf", "18", "-preset", "medium",
                 "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", out])


def erase_region(path: str, params: Mapping[str, Any], out: str) -> None:
    facts = _probe(path)
    x, y, width, height = canvas_tools.erase_box(params, facts["width"], facts["height"])
    mode = canvas_tools.erase_mode(params)
    if mode == "delogo":
        graph = ["-vf", f"delogo=x={x}:y={y}:w={width}:h={height}"]
    else:
        # Privacy: the box alone is blurred or pixelated and laid back over the frame at the same place.
        rules = prompt_data.value("canvas_tools", "erase_modes")
        if mode == "blur":
            # The colour planes are half the size, so their radius has to be half as large to fit the box.
            radius = max(1, min(int(rules["blur_radius"]), min(width, height) // 2 - 1))
            chroma = max(1, min(radius // 2, min(width, height) // 4 - 1))
            covered = f"boxblur=lr={radius}:lp=3:cr={chroma}:cp=3"
        else:
            cells = int(rules["mosaic_cells"])
            covered = (f"scale=max(1\\,trunc(iw/{cells})):max(1\\,trunc(ih/{cells})):flags=neighbor,"
                       f"scale={width}:{height}:flags=neighbor")
        graph = ["-filter_complex", f"[0:v]crop={width}:{height}:{x}:{y},{covered}[box];[0:v][box]overlay={x}:{y}[out]", "-map", "[out]", "-map", "0:a?"]
    _run_ffmpeg(["-i", path, *graph, "-c:v", "libx264", "-crf", "18", "-preset", "medium",
                 "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", out])


def extract_audio(path: str, out: str) -> None:
    if not _probe(path)["has_audio"]:
        raise CanvasToolError(_text_of("extract_audio.text"))
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
            raise CanvasToolError(_text_of("extract_frame.text").format(facts['duration']))
        _run_ffmpeg(["-ss", f"{at:.3f}", "-i", path, "-frames:v", "1", out])
    if not os.path.exists(out):
        raise RuntimeError(_text_of("extract_frame.text.2"))


def to_gif(path: str, params: Mapping[str, Any], out: str) -> None:
    fps = int(canvas_tools.number(params, "fps", 12, 4, 24))
    width = int(canvas_tools.number(params, "width", 480, 120, 960))
    seconds = canvas_tools.number(params, "seconds", _DEFAULT_GIF_SECONDS, 0.5, 30)
    graph = f"fps={fps},scale={width}:-2:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer"
    _run_ffmpeg(["-t", f"{seconds:.2f}", "-i", path, "-filter_complex", graph, "-loop", "0", out])


def cut_out_frames(path: str, params: Mapping[str, Any], tag: str, tool: CanvasTool) -> dict[str, Any]:
    """抠像序列帧: the clip keyed out into a ZIP of same-sized transparent PNGs; the picture shown is its sprite sheet."""
    preview, url = _output_path(tag, tool, "png")
    archive, archive_url = _output_path(tag, tool, "zip")
    try:
        with tempfile.TemporaryDirectory(prefix="canvas_sprite_") as frames:
            manifest = sprite_frames.cut_out(path, params, facts=_probe(path), run_ffmpeg=_run_ffmpeg, scratch=frames, zip_out=archive, preview_out=preview)
    except BaseException:
        # A refused or failed run leaves nothing half-written under /media.
        for leftover in (preview, archive):
            if os.path.exists(leftover):
                os.remove(leftover)
        raise
    return {"url": url, "zip": archive_url, "sprite": manifest}


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
    if tool.id == "reference_remake":
        # A fixed wording put together here: no model, no file.
        return {"text": canvas_tools.remake_prompt(params, prompt)}
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
    if tool.id == "move_sheet":
        # 招式分解图按 3:4 出：画格才装得下横着的长兵器(move_sheets.json 的 size)。
        size = move_sheets.sheet_size()
    if tool.id == "mood_frame":
        references = mood_references(references[:3], scratch)
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
        raise RuntimeError(_text_of("_run_image.text"))
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
        return _write(tool, prompt, model, tag, task_id, drama, params=params)
    if tool.id == "voice_isolate":
        return _isolate_voice(tool, inputs, tag, scratch)
    if tool.id == "shot_analysis":
        return _analyze_shots(tool, inputs, model, task_id, drama, scratch)
    if tool.id == "character_extract":
        return _extract_character(inputs, prompt, model, task_id, drama, scratch)
    picture = _image_bytes_uri(_materialize(_pictures(inputs)[0], ".png", scratch), drama)
    system, question = {
        "reverse_prompt": (canvas_tools.REVERSE_SYSTEM, canvas_tools.REVERSE_PROMPT),
        "mark_detect": (canvas_tools.MARK_SYSTEM, canvas_tools.MARK_PROMPT),
        "frame_review": (canvas_tools.REVIEW_SYSTEM, canvas_tools.REVIEW_PROMPT.format(extra=_text_of("_run_model.extra").format(prompt) if prompt else "")),
    }[tool.id]
    answer, used = _ask_vision(drama, model, system, question, picture, task_id)
    return {"text": answer, "model": used}


def _extract_character(inputs: studio_canvas.Inputs, prompt: str, model: str, task_id: str, drama: Any, scratch: str) -> dict[str, Any]:
    """角色设定提取：连了图就让看图模型照图写(``prompt`` 是补充说明)；只有文字就让文本模型把描述改写成同样格式的一段。"""
    pictures = _pictures(inputs)
    question = canvas_tools.character_question(prompt, picture=bool(pictures))
    if pictures:
        picture = _image_bytes_uri(_materialize(pictures[0], ".png", scratch), drama)
        answer, used = _ask_vision(drama, model, canvas_tools.CHARACTER_SYSTEM, question, picture, task_id)
        return {"text": answer, "model": used}
    with usage_ledger.bind_task(task_id, "canvas_tool"):
        answer = drama.gateway.call_llm(model, canvas_tools.CHARACTER_SYSTEM, question, "", max_tokens=_WRITER_TOKENS)
    if not answer:
        raise RuntimeError(_text_of("_write.text.2"))
    return {"text": str(answer).strip(), "model": model}


_WRITERS = {
    "action_breakdown": (action_grammar.BREAKDOWN_SYSTEM, "{story}"),
    "link_design": (canvas_tools.LINK_SYSTEM, canvas_tools.LINK_PROMPT),
    "frame_bridge": (canvas_tools.FRAME_BRIDGE_SYSTEM, canvas_tools.FRAME_BRIDGE_PROMPT),
    "script_write": (canvas_tools.SCRIPT_SYSTEM, canvas_tools.SCRIPT_PROMPT),
    "shot_table": (canvas_tools.SHOT_TABLE_SYSTEM, canvas_tools.SHOT_TABLE_PROMPT),
    "svg_art": (canvas_tools.SVG_SYSTEM, canvas_tools.SVG_PROMPT),
    "html_page": (canvas_tools.HTML_SYSTEM, canvas_tools.HTML_PROMPT),
}


def _write(tool: CanvasTool, prompt: str, model: str, tag: str, task_id: str, drama: Any, *, params: Mapping[str, Any] | None = None) -> dict[str, Any]:
    story = " ".join(str(prompt or "").split()) if tool.id != "shot_table" else str(prompt or "").strip()
    if not story:
        raise CanvasToolError(_text_of("_write.text"))
    system, template = _WRITERS[tool.id]
    # A shot table is asked for as many shots as the node or its text says (「镜头数：3」「三个镜头」), else as the story needs.
    asked = canvas_tools.asked_shots(params or {}, story) if tool.id == "shot_table" else 0
    if tool.id == "action_breakdown":
        question = action_grammar.breakdown_prompt(story)
    elif tool.id == "shot_table":
        question = canvas_tools.shot_table_question(story, asked)
    else:
        question = template.format(story=story)
    with usage_ledger.bind_task(task_id, "canvas_tool"):
        answer = drama.gateway.call_llm(model, system, question, "", max_tokens=_WRITER_TOKENS)
    if not answer:
        raise RuntimeError(_text_of("_write.text.2"))
    if tool.id == "action_breakdown":
        try:
            return {"text": action_grammar.parse_breakdown(answer)}
        except ValueError as error:
            raise CanvasToolError(str(error)) from error
    if tool.id in {"script_write", "link_design", "frame_bridge"}:
        return {"text": str(answer).strip()}
    if tool.id == "shot_table":
        shots = canvas_tools.parse_shots(answer)
        # Each character seen in more than one shot gets the words for a look sheet of their own (sheet_prompt).
        cast = canvas_tools.with_sheets(canvas_tools.parse_cast(answer), shots)
        # ``shots`` keeps each row whole (length, who is in it, lines) and ``cast`` each character's look, for 铺成镜头:
        # a first frame feeding a video node per shot, one face per character. ``asked`` lets the node say when the
        # model gave a different number of shots than it was asked for.
        # ``line_order``: lines the model moved against the script's order, so the node can say so (a rerun usually fixes it).
        moved = canvas_tools.lines_out_of_order(story, shots)
        return {"text": canvas_tools.shots_text(shots), "beats": canvas_tools.shots_as_beats(shots, cast), "shots": shots, "cast": cast,
                **({"asked": asked} if asked else {}), **({"line_order": moved} if moved else {})}
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
    note = _text_of("_analyze_shots.note").format(len(starts), _MAX_SHOTS_IN_SHEET) if len(starts) > _MAX_SHOTS_IN_SHEET else ""
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
    elif tool.id == "color_card":
        out, url = _output_path(tag, tool, "png")
        color_card([_materialize(picture, ".png", scratch) for picture in _pictures(inputs)[:2]], int(canvas_tools.number(params, "colors", 8, 6, 10)), out)
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
    elif tool.id == "sprite_frames":
        return cut_out_frames(_materialize(inputs.ref_videos[0], ".mp4", scratch), params, tag, tool)
    else:
        raise CanvasToolError(_text_of("_run_local.text").format(tool.label))
    return {"url": url}


__all__ = ["run_tool"]
