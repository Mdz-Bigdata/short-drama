# -*- coding: utf-8 -*-
"""A clip on a flat background cut out into a transparent frame sequence (the canvas tool ``sprite_frames``).

The key colour is turned into alpha by ffmpeg (``chromakey`` for a saturated colour, ``colorkey`` for a
grey one); PIL then finds ONE crop box for the whole sequence — the union of every frame's visible
bounding box, padded on the left, top and right — so the figure does not jitter when the frames are
played back. The box's bottom edge is the lowest visible pixel of the whole sequence: the shared foot
baseline. The frames go into a ZIP as numbered PNGs with a manifest, and into one row-major sprite
sheet when that stays under a pixel limit.

Local ffmpeg and PIL only: no model is called and nothing is billed. Wording, colour tables and limits
are data, in ``app/data/prompt/sprite_frames.json``. ffmpeg itself is run by the caller
(``app.service.canvas_tool_ops``), which owns the binary, the timeout and the failure wording.
"""

from __future__ import annotations

import io
import json
import math
import os
import re
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageChops, ImageFilter

from app.core import prompt_data
from app.core.canvas_tools import CanvasToolError, number

_DATA = "sprite_frames"
_HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")
_SCRATCH_PATTERN = "keyed_%05d.png"
_SCRATCH_PREFIX = "keyed_"

Colour = tuple[int, int, int]
Box = tuple[int, int, int, int]


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/sprite_frames.json."""
    return prompt_data.text(_DATA, key)


def _table(key: str) -> Mapping[str, Any]:
    return prompt_data.value(_DATA, key)


@dataclass(frozen=True)
class Settings:
    # ``auto`` or a key of the colour table or ``custom``; ``colour`` is None only for ``auto``.
    picked: str
    colour: Colour | None
    tolerance: float
    fps: int
    max_frames: int


def parse_hex(text: Any) -> Colour | None:
    match = _HEX.match(str(text or "").strip())
    if not match:
        return None
    digits = match.group(1)
    return (int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16))


def hex_of(colour: Colour) -> str:
    return "#{:02x}{:02x}{:02x}".format(*colour)


def settings_of(params: Mapping[str, Any]) -> Settings:
    """What the node asked for, each number held inside its bounds; a custom colour that is not a colour is refused."""
    options = _table("options")
    colours = _table("key_colours")
    picked = str(params.get("key") or options["key"])
    colour: Colour | None = None
    if picked == options["key_custom"]:
        written = params.get("key_hex") or options["key_hex"]
        colour = parse_hex(written)
        if colour is None:
            raise CanvasToolError(_text_of("error.bad_hex").format(written))
    elif picked in colours:
        colour = parse_hex(colours[picked])
    else:
        picked = str(options["key"])

    def bounded(key: str) -> float:
        rule = options[key]
        return number(params, key, rule["default"], rule["min"], rule["max"])

    return Settings(picked=picked, colour=colour, tolerance=bounded("tolerance"), fps=int(bounded("fps")), max_frames=int(bounded("max_frames")))


# ---------------------------------------------------------------------------- the key colour
def corner_colour(image: Image.Image) -> Colour:
    """The dominant colour of the four corners; refused when the corners are not one flat colour."""
    rules = _table("auto")
    picture = image.convert("RGB")
    side = max(int(rules["patch_min_px"]), round(min(picture.size) * float(rules["patch_percent"]) / 100))
    side = max(1, min(side, picture.width, picture.height))
    pixels: list[Colour] = []
    for left in (0, picture.width - side):
        for top in (0, picture.height - side):
            raw = picture.crop((left, top, left + side, top + side)).tobytes()
            pixels.extend(zip(raw[0::3], raw[1::3], raw[2::3]))
    buckets: dict[Colour, list[Colour]] = {}
    for pixel in pixels:
        buckets.setdefault((pixel[0] >> 4, pixel[1] >> 4, pixel[2] >> 4), []).append(pixel)
    most = max(buckets.values(), key=len)
    centre = tuple(round(sum(pixel[channel] for pixel in most) / len(most)) for channel in range(3))
    reach = float(rules["spread"]) ** 2
    near = sum(1 for pixel in pixels if sum((pixel[channel] - centre[channel]) ** 2 for channel in range(3)) <= reach)
    if near * 100 < len(pixels) * float(rules["min_share_percent"]):
        raise CanvasToolError(_text_of("error.corners_differ"))
    return (int(centre[0]), int(centre[1]), int(centre[2]))


def chroma_of(colour: Colour) -> float:
    """How far a colour sits from grey on the UV plane (0–~180): what decides between chromakey and colorkey."""
    red, green, blue = colour
    u = -0.169 * red - 0.331 * green + 0.5 * blue
    v = 0.5 * red - 0.419 * green - 0.081 * blue
    return math.hypot(u, v)


def key_filter(colour: Colour, tolerance: float) -> dict[str, Any]:
    """The ffmpeg filter that turns ``colour`` into alpha, and the numbers it was given."""
    rules = _table("keying")
    low, high = float(rules["similarity_min"]), float(rules["similarity_max"])
    similarity = round(low + (high - low) * max(0.0, min(100.0, tolerance)) / 100, 4)
    blend = round(min(float(rules["blend_max"]), similarity * float(rules["blend_ratio"])), 4)
    # chromakey looks at chroma alone, so shading on the backdrop still keys; a grey backdrop has no chroma to look at.
    method = "chromakey" if chroma_of(colour) >= float(rules["chroma_min"]) else "colorkey"
    target = "0x{:02X}{:02X}{:02X}".format(*colour)
    graph = f"format=yuva444p,chromakey={target}:{similarity}:{blend}" if method == "chromakey" else f"format=rgba,colorkey={target}:{similarity}:{blend}"
    return {"method": method, "similarity": similarity, "blend": blend, "graph": f"{graph},format=rgba"}


def spill_family(colour: Colour) -> str:
    """Which of the three backdrops with a known despill this colour is; ``""`` for any other (no despill is done)."""
    red, green, blue = colour
    margin = int(_table("despill")["dominance"])
    if green - max(red, blue) >= margin:
        return "green"
    if min(red, blue) - green >= margin:
        return "magenta"
    if blue - max(red, green) >= margin:
        return "blue"
    return ""


_HALF = [value // 2 for value in range(256)]


def _despill(red: Image.Image, green: Image.Image, blue: Image.Image, alpha: Image.Image, family: str) -> tuple[Image.Image, Image.Image, Image.Image]:
    """The key colour's tint taken off the pixels within a few pixels of transparency; the inside is left alone."""
    if family == "green":
        fixed = (red, ImageChops.darker(green, ImageChops.lighter(red, blue)), blue)
    elif family == "blue":
        fixed = (red, green, ImageChops.darker(blue, ImageChops.lighter(red, green)))
    elif family == "magenta":
        # Magenta is red and blue together above green: half the excess comes off those two, half goes onto green.
        half = ImageChops.subtract(ImageChops.darker(red, blue), green).point(_HALF)
        fixed = (ImageChops.subtract(red, half), ImageChops.add(green, half), ImageChops.subtract(blue, half))
    else:
        return red, green, blue
    reach = max(1, int(_table("despill")["edge_px"]))
    edge = alpha.filter(ImageFilter.MinFilter(2 * reach + 1)).point([255] * 255 + [0])
    return (Image.composite(fixed[0], red, edge), Image.composite(fixed[1], green, edge), Image.composite(fixed[2], blue, edge))


# ---------------------------------------------------------------------------- the one crop box
def union_box(boxes: Sequence[Box | None], width: int, height: int) -> Box | None:
    """One box holding every frame's visible pixels, padded left, top and right; its bottom is the foot baseline, unpadded."""
    seen = [box for box in boxes if box]
    if not seen:
        return None
    left, top = min(box[0] for box in seen), min(box[1] for box in seen)
    right, bottom = max(box[2] for box in seen), max(box[3] for box in seen)
    rules = _table("crop")
    pad = max(int(rules["padding_min_px"]), round(max(right - left, bottom - top) * float(rules["padding_percent"]) / 100))
    return (max(0, left - pad), max(0, top - pad), min(width, right + pad), bottom)


def sheet_grid(count: int, frame_width: int, frame_height: int) -> tuple[int, int] | None:
    """Columns and rows of a near-square row-major sheet, or None when it would pass the pixel limit."""
    rules = _table("sheet")
    columns = max(1, min(count, math.ceil(math.sqrt(count * frame_height / frame_width))))
    rows = math.ceil(count / columns)
    width, height = columns * frame_width, rows * frame_height
    if max(width, height) > int(rules["max_side"]) or width * height > int(rules["max_pixels"]):
        return None
    return columns, rows


def expected_frames(duration: float, fps: int) -> int:
    return max(1, round(duration * fps))


def check_size(facts: Mapping[str, Any], settings: Settings) -> int:
    """How many frames the clip gives at this rate; refused, with what to change, when that is too many or too heavy."""
    duration = float(facts.get("duration") or 0)
    if duration <= 0:
        raise CanvasToolError(_text_of("error.no_duration"))
    frames = expected_frames(duration, settings.fps)
    if frames > settings.max_frames:
        ceiling = int(_table("options")["max_frames"]["max"])
        raise CanvasToolError(_text_of("error.too_many_frames").format(duration, settings.fps, frames, settings.max_frames, ceiling))
    width, height = int(facts.get("width") or 0), int(facts.get("height") or 0)
    if width * height * frames > int(_table("limits")["max_source_pixels"]):
        raise CanvasToolError(_text_of("error.too_heavy").format(width, height, frames))
    return frames


# ---------------------------------------------------------------------------- one run
def cut_out(
    path: str, params: Mapping[str, Any], *, facts: Mapping[str, Any], run_ffmpeg: Callable[[list[str]], Any], scratch: str, zip_out: str, preview_out: str,
) -> dict[str, Any]:
    """Key ``path`` out and write the ZIP and the preview picture; answers with the manifest (also inside the ZIP).

    ``facts`` is the clip's width, height and duration; ``run_ffmpeg`` runs ffmpeg with the given arguments and raises
    when it fails. ``preview_out`` gets the sprite sheet, or the first frame when the sheet would be too large.
    """
    settings = settings_of(params)
    check_size(facts, settings)
    colour = settings.colour
    if colour is None:
        first = os.path.join(scratch, "first.png")
        run_ffmpeg(["-i", path, "-an", "-frames:v", "1", first])
        if not os.path.exists(first):
            raise RuntimeError(_text_of("error.no_frames"))
        with Image.open(first) as image:
            colour = corner_colour(image)
    keying = key_filter(colour, settings.tolerance)
    # One frame past the limit is asked for, so a clip that runs longer than its header says is caught rather than cut short.
    run_ffmpeg(["-i", path, "-an", "-vf", f"fps={settings.fps},{keying['graph']}", "-frames:v", str(settings.max_frames + 1), os.path.join(scratch, _SCRATCH_PATTERN)])
    sources = sorted(os.path.join(scratch, name) for name in os.listdir(scratch) if name.startswith(_SCRATCH_PREFIX))
    if not sources:
        raise RuntimeError(_text_of("error.no_frames"))
    if len(sources) > settings.max_frames:
        ceiling = int(_table("options")["max_frames"]["max"])
        raise CanvasToolError(_text_of("error.too_many_frames").format(float(facts.get("duration") or 0), settings.fps, len(sources), settings.max_frames, ceiling))

    floor = max(1, min(255, int(prompt_data.number(_DATA, "alpha_floor"))))
    visible_lut = [0] * floor + [255] * (256 - floor)
    alpha_lut = [0] * floor + list(range(floor, 256))
    boxes: list[Box | None] = []
    cleared = total = 0
    width = height = 0
    for source in sources:
        with Image.open(source) as image:
            alpha = image.convert("RGBA").getchannel("A")
        width, height = alpha.size
        cleared += sum(alpha.histogram()[:floor])
        total += width * height
        boxes.append(alpha.point(visible_lut).getbbox())
    box = union_box(boxes, width, height)
    if box is None:
        raise CanvasToolError(_text_of("error.all_keyed"))
    if cleared * 100 < total * float(_table("limits")["min_transparent_percent"]):
        raise CanvasToolError(_text_of("error.nothing_keyed").format(hex_of(colour)))

    frame_width, frame_height = box[2] - box[0], box[3] - box[1]
    family = spill_family(colour)
    files = _table("files")
    grid = sheet_grid(len(sources), frame_width, frame_height)
    sheet = Image.new("RGBA", (grid[0] * frame_width, grid[1] * frame_height), (0, 0, 0, 0)) if grid else None
    manifest: dict[str, Any] = {
        "frame_width": frame_width, "frame_height": frame_height, "count": len(sources), "fps": settings.fps,
        "first": str(files["frame"]).format(1), "last": str(files["frame"]).format(len(sources)),
        "source": {"width": width, "height": height},
        "crop": {"x": box[0], "y": box[1], "width": frame_width, "height": frame_height},
        # The foot line: the lowest visible pixel of the whole sequence sits just above it. It is the bottom edge of every frame.
        "baseline": {"frame_y": frame_height, "source_y": box[3]},
        "key": {"colour": hex_of(colour), "picked": settings.picked, "method": keying["method"], "tolerance": settings.tolerance,
                "similarity": keying["similarity"], "blend": keying["blend"]},
        "despill": family or "none",
        "sheet": {"file": str(files["sheet"]), "columns": grid[0], "rows": grid[1], "order": "row-major"} if grid else None,
    }
    black = Image.new("L", (frame_width, frame_height), 0)
    with zipfile.ZipFile(zip_out, "w", zipfile.ZIP_STORED) as archive:
        for index, source in enumerate(sources):
            with Image.open(source) as image:
                red, green, blue, alpha = image.convert("RGBA").crop(box).split()
            alpha = alpha.point(alpha_lut)
            red, green, blue = _despill(red, green, blue, alpha, family)
            # A keyed-out pixel keeps the backdrop's colour under its zero alpha, and a renderer that filters would bleed it back in.
            shown = alpha.point([0] + [255] * 255)
            frame = Image.merge("RGBA", (Image.composite(red, black, shown), Image.composite(green, black, shown), Image.composite(blue, black, shown), alpha))
            held = io.BytesIO()
            frame.save(held, "PNG")
            archive.writestr(str(files["frame"]).format(index + 1), held.getvalue())
            if sheet is not None and grid:
                row, column = divmod(index, grid[0])
                sheet.paste(frame, (column * frame_width, row * frame_height))
            elif index == 0:
                frame.save(preview_out, "PNG")
        if sheet is not None:
            sheet.save(preview_out, "PNG")
            archive.write(preview_out, str(files["sheet"]))
        archive.writestr(str(files["manifest"]), json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


__all__ = [
    "Settings", "check_size", "chroma_of", "corner_colour", "cut_out", "expected_frames", "hex_of", "key_filter", "parse_hex", "settings_of",
    "sheet_grid", "spill_family", "union_box",
]
