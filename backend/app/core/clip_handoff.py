# -*- coding: utf-8 -*-
"""镜头衔接质检：相邻两镜生成出来的视频，在切点两边接不接得上。

分镜规划时已经按文字查过方向、动作和落幅(``shot_transitions``)，也把「这一镜怎么收」写进了提示词；
模型照不照做是另一回事。这里量真正出来的片子：每段的开头和结尾各取一小段，缩成很小的灰度帧，量三样东西——

* **往哪边动**：整幅画面的平移(背景往左流＝镜头往右跟)，和去掉平移之后还在动的像素(主体)往哪边漂；
* **停没停**：运动量、最后一段是否完全定格、结尾附近有没有一帧突变(模型自己切了一刀)；
* **主体在哪**：运动像素的重心在画面哪一侧，是否正贴着画面边出去或进来。

再拿相邻两段比：运动方向是否连续、结尾是否适合计划里的接法(运动接运动不能停住，接稳定画面要先落幅)、
出画入画的方向接不接得上。只量画面，不懂剧情：结论是提示，不自动拒收、不重出。只用 ffmpeg 和标准库；
阈值与说法在 app/data/prompt/clip_handoff.json。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from app.core import prompt_data

_DATA = "clip_handoff"
Heading = Literal["left", "right", ""]
Side = Literal["left", "right", "center", ""]


def _text(key: str) -> str:
    return prompt_data.text(_DATA, key)


def _number(key: str) -> float:
    return float(prompt_data.value(_DATA, key))


def _label(table: str, key: str) -> str:
    return str(prompt_data.value(_DATA, table)[key])


class HandoffError(RuntimeError):
    """A clip could not be measured (missing file, unreadable video)."""


# ---------------------------------------------------------------------------- frames


def _tools() -> tuple[str, str]:
    from app.core import media_compositor

    return media_compositor._ffmpeg(), media_compositor._ffprobe()


def _size(path: str, probe: str) -> tuple[int, int, float]:
    try:
        raw = subprocess.run(
            [probe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration", "-of", "json", path],
            capture_output=True, text=True, timeout=20,
        ).stdout
        info = json.loads(raw or "{}")
        stream = (info.get("streams") or [{}])[0]
        return int(stream["width"]), int(stream["height"]), float((info.get("format") or {}).get("duration") or 0)
    except (KeyError, ValueError, TypeError, subprocess.SubprocessError, OSError) as error:
        raise HandoffError(_text("probe_failed")) from error


def frames(path: str, end: Literal["head", "tail"]) -> tuple[list[bytes], int, int, float]:
    """(grey frames of the opening or closing window, width, height, fps)."""
    if not path or not os.path.exists(path):
        raise HandoffError(_text("missing_file"))
    ffmpeg, probe = _tools()
    if not ffmpeg or not probe:
        raise HandoffError(_text("probe_failed"))
    width, height, duration = _size(path, probe)
    long_side = int(_number("long_side"))
    if width >= height:
        w, h = long_side, max(8, round(long_side * height / width / 2) * 2)
    else:
        w, h = max(8, round(long_side * width / height / 2) * 2), long_side
    seconds = min(_number("window_seconds"), max(0.2, duration / 2)) if duration else _number("window_seconds")
    fps = _number("fps")
    window = ["-sseof", f"-{seconds:.3f}", "-i", path] if end == "tail" else ["-i", path, "-t", f"{seconds:.3f}"]
    try:
        raw = subprocess.run(
            [ffmpeg, "-v", "error", *window, "-vf", f"fps={fps:g},scale={w}:{h}:flags=area,format=gray", "-f", "rawvideo", "-"],
            capture_output=True, timeout=60,
        ).stdout
    except (subprocess.SubprocessError, OSError) as error:
        raise HandoffError(_text("probe_failed")) from error
    size = w * h
    out = [raw[index:index + size] for index in range(0, len(raw) - size + 1, size)]
    if len(out) < 3:
        raise HandoffError(_text("too_short"))
    return out, w, h, fps


# ---------------------------------------------------------------------------- one window


def _mean_diff(a: bytes, b: bytes, w: int, h: int, dx: int, dy: int) -> float:
    """Mean grey difference of b against a shifted by (dx, dy), over the overlap, every second pixel."""
    total = count = 0
    for y in range(max(0, dy), min(h, h + dy), 2):
        row_b, row_a = y * w, (y - dy) * w
        for x in range(max(0, dx), min(w, w + dx), 2):
            total += abs(b[row_b + x] - a[row_a + x - dx])
            count += 1
    return total / count if count else 255.0


def _band(frame: bytes, w: int, top: int, bottom: int) -> bytes:
    return frame[top * w: bottom * w]


def _band_shift(a: bytes, b: bytes, w: int, h: int) -> int | None:
    """The horizontal shift that explains one band; ``None`` when no shift explains it clearly better than none."""
    reach = max(1, int(w * _number("shift_ratio")))
    still = _mean_diff(a, b, w, h, 0, 0)
    best_dx, best = 0, still
    for dx in range(-reach, reach + 1):
        score = _mean_diff(a, b, w, h, dx, 0)
        if score < best:
            best_dx, best = dx, score
    return best_dx if best_dx and best < still * _number("pan_gain") else (0 if still <= _number("frozen_diff") * 4 else None)


def _shift(a: bytes, b: bytes, w: int, h: int) -> tuple[int, int, float]:
    """The camera's horizontal move from a to b (content moved by dx), and the difference left after it.

    Measured on the top and the bottom band apart: the background fills them, the subject seldom does.
    A move is the camera's only when both bands agree on it; a subject crossing a plain background moves
    one band at most, and must not read as a pan.
    """
    band = max(2, int(h * _number("band_ratio")))
    top = _band_shift(_band(a, w, 0, band), _band(b, w, 0, band), w, band)
    bottom = _band_shift(_band(a, w, h - band, h), _band(b, w, h - band, h), w, band)
    dx = 0
    if top and bottom and (top > 0) == (bottom > 0):
        dx = round((top + bottom) / 2)
    return dx, 0, _mean_diff(a, b, w, h, dx, 0)


def _moving(a: bytes, b: bytes, w: int, h: int, dx: int, dy: int) -> tuple[float, float | None]:
    """(share of pixels still moving after the shift, their mean x as 0…1 or None)."""
    level = _number("moving_level")
    moving = xs = count = 0
    for y in range(max(0, dy), min(h, h + dy)):
        row_b, row_a = y * w, (y - dy) * w
        for x in range(max(0, dx), min(w, w + dx)):
            count += 1
            if abs(b[row_b + x] - a[row_a + x - dx]) > level:
                moving += 1
                xs += x
    share = moving / count if count else 0.0
    return share, ((xs / moving) / max(1, w - 1) if moving else None)


@dataclass
class Profile:
    """What the picture does in one opening or closing window."""

    heading: Heading = ""
    pan: Heading = ""
    energy: float = 0.0
    still: bool = False
    frozen_seconds: float = 0.0
    jump: bool = False
    position: Side = ""
    position_x: float | None = None
    edge: Side = ""
    camera_moving: bool = False
    camera_diff: float = 0.0
    measured: bool = True
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _side(x: float | None) -> Side:
    if x is None:
        return ""
    return "left" if x < 0.4 else "right" if x > 0.6 else "center"


def profile(grey: Sequence[bytes], w: int, h: int, fps: float, end: Literal["head", "tail"]) -> Profile:
    """Measure one window: which way it moves, whether it stops or freezes, where the moving subject is."""
    band = max(2, int(h * _number("band_ratio")))
    raws, framewide = [], []
    frozen_run = longest_tail_frozen = 0
    # Neighbouring frames: a freeze, a sudden jump, and whether the whole picture changes.
    for a, b in zip(grey, grey[1:]):
        raw = _mean_diff(a, b, w, h, 0, 0)
        raws.append(raw)
        # The camera moves the whole picture (pan, push, shake): top and bottom change together.
        # An actor moving in a locked-off frame changes one part of it.
        framewide.append(min(
            _mean_diff(_band(a, w, 0, band), _band(b, w, 0, band), w, band, 0, 0),
            _mean_diff(_band(a, w, h - band, h), _band(b, w, h - band, h), w, band, 0, 0),
        ))
        frozen_run = frozen_run + 1 if raw <= _number("frozen_diff") else 0
        longest_tail_frozen = frozen_run
    ordered = sorted(raws)
    typical = ordered[len(ordered) // 2] if ordered else 0.0
    jump = any(raw >= _number("jump_diff") and raw >= typical * _number("jump_ratio") for raw in raws)
    # Frames a third of a second apart: a slow pan moves a few pixels there, not a fraction of one.
    gap = max(1, round(fps * _number("pair_gap_seconds")))
    pairs = [(index, grey[index], grey[index + gap]) for index in range(0, len(grey) - gap)]
    pans, energies, centres = [], [], []
    for index, a, b in pairs:
        dx, dy, _left_over = _shift(a, b, w, h)
        share, centre = _moving(a, b, w, h, dx, dy)
        pans.append(dx)
        energies.append(share + abs(dx) / max(1, w))
        centres.append((index + gap / 2, centre) if share >= _number("min_moving") and centre is not None else None)
    span = gap / fps
    # Content moving left means the camera follows something heading right.
    pan_speed = -(sum(pans) / len(pans)) / max(1, w) / span if pans else 0.0
    found = [item for item in centres if item is not None]
    drift = 0.0
    if len(found) >= 2:
        (t0, x0), (t1, x1) = found[0], found[-1]
        drift = (x1 - x0) / ((t1 - t0) / fps) if t1 > t0 else 0.0
    pan: Heading = "right" if pan_speed > _number("pan_speed") else "left" if pan_speed < -_number("pan_speed") else ""
    moving = pan_speed + drift
    heading: Heading = ""
    if abs(pan_speed) > _number("pan_speed") or abs(drift) > _number("drift_speed"):
        heading = "right" if moving > 0 else "left"
    energy = sum(energies) / len(energies) if energies else 0.0
    # Where the subject is at the cut: the last measured centre of a closing window, the first of an opening one.
    edge_x = (found[-1][1] if end == "tail" else found[0][1]) if found else None
    edge_band = _number("edge")
    edge: Side = ""
    if edge_x is not None and heading:
        if end == "tail" and ((heading == "right" and edge_x > 1 - edge_band) or (heading == "left" and edge_x < edge_band)):
            edge = heading
        if end == "head" and ((heading == "right" and edge_x < edge_band) or (heading == "left" and edge_x > 1 - edge_band)):
            edge = "left" if heading == "right" else "right"
    frozen = longest_tail_frozen / fps if end == "tail" else 0.0
    camera = sum(framewide) / len(framewide) if framewide else 0.0
    return Profile(
        camera_moving=bool(pan) or camera >= _number("camera_diff"), camera_diff=round(camera, 2),
        # A small subject crossing the frame changes few pixels; it is still moving when it has a heading.
        heading=heading, pan=pan, energy=round(energy, 4), still=energy <= _number("still_energy") and not heading,
        frozen_seconds=round(frozen, 2) if frozen >= _number("frozen_seconds") else 0.0, jump=jump,
        position=_side(edge_x), position_x=round(edge_x, 3) if edge_x is not None else None, edge=edge,
    )


def measure(path: str, end: Literal["head", "tail"]) -> Profile:
    """The opening or closing window of a local clip; an unreadable clip is a profile marked unmeasured."""
    try:
        grey, w, h, fps = frames(path, end)
    except HandoffError as error:
        return Profile(measured=False, reason=str(error))
    return profile(grey, w, h, fps, end)


# ---------------------------------------------------------------------------- one cut


@dataclass
class Planned:
    """What the storyboard says about the cut (all optional)."""

    same_scene: bool = True
    shared_subject: bool = True
    motion_join: str = ""
    turns: bool = False
    # The shot before says its move settles at the end (推至…停稳、横移后定住): a still ending is the plan.
    ends_settled: bool = False
    # The shot after says it opens on a held frame (固定起幅…): a still opening is the plan.
    opens_held: bool = False
    # A dissolve or a fade needs a settled picture on both sides, whatever the cameras do.
    optical: bool = False


@dataclass
class HandoffReport:
    verdict: Literal["good", "suspect", "unknown"]
    label: str
    findings: list[dict[str, str]] = field(default_factory=list)
    tail: str = ""
    head: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def describe(item: Profile, end: Literal["head", "tail"]) -> str:
    if not item.measured:
        return ""
    if item.frozen_seconds:
        state = _text("state_frozen").format(seconds=item.frozen_seconds)
    elif item.still:
        state = _text("state_still")
    else:
        state = _text("state_moving")
    if item.jump:
        state += _text("state_jump")
    border = ""
    if item.edge:
        border = _text("exit_line" if end == "tail" else "entry_line").format(side=_label("side", item.edge))
    return _text("tail_line" if end == "tail" else "head_line").format(
        heading=_label("heading", item.heading), state=state, exit=border, entry=border,
    )


def compare(tail: Profile, head: Profile, planned: Planned | None = None) -> HandoffReport:
    """Does the end of one clip hand over to the start of the next?"""
    plan = planned or Planned()
    if not tail.measured or not head.measured:
        reason = tail.reason or head.reason
        return HandoffReport("unknown", _label("verdict", "unknown"), [{"code": "unknown", "text": _text("unknown_detail").format(reason=reason)}])
    found: list[dict[str, str]] = []
    # 1. motion direction continues across the cut
    if plan.same_scene and not plan.turns:
        if plan.shared_subject and tail.heading and head.heading and tail.heading != head.heading:
            found.append({"code": "direction", "text": _text("finding_direction").format(a=_label("heading", tail.heading), b=_label("heading", head.heading))})
        elif tail.pan and head.pan and tail.pan != head.pan:
            found.append({"code": "pan", "text": _text("finding_pan").format(a=_label("heading", tail.pan)[-1], b=_label("heading", head.pan)[-1])})
    # 2. the ending suits the planned way in
    join = plan.motion_join
    # A hold into a still shot is the planned settle; a freeze before movement reads as a stalled video.
    if tail.frozen_seconds and not head.still:
        found.append({"code": "frozen", "text": _text("finding_frozen").format(seconds=tail.frozen_seconds)})
    # Carrying a move through the cut is asked of a hard cut inside one scene only.
    carried = join == "moving_to_moving" and plan.same_scene and not plan.optical
    if carried and not plan.ends_settled and (tail.still or tail.frozen_seconds):
        state = _text("state_frozen_word") if tail.frozen_seconds else _text("state_still_word")
        found.append({"code": "wants_motion", "text": _text("finding_wants_motion").format(state=state)})
    if carried and not plan.opens_held and head.still:
        found.append({"code": "head_still", "text": _text("finding_head_still")})
    # Settling is about the camera: an actor still moving in a locked frame has settled.
    wants_settle = plan.optical or join in {"moving_to_static", "static_to_static", "static_to_moving"}
    if wants_settle and tail.camera_moving and not tail.frozen_seconds:
        found.append({"code": "wants_settle", "text": _text("finding_wants_settle")})
    if tail.jump:
        found.append({"code": "jump", "text": _text("finding_jump")})
    # 3. the subject leaves on one side and comes back in on the other
    # A written turn brings the subject back on the side it left from; that is the plan, not a slip.
    if plan.same_scene and plan.shared_subject and not plan.turns and tail.edge and head.edge and tail.edge == head.edge:
        found.append({"code": "exit_entry", "text": _text("finding_exit_entry").format(exit=_label("side", tail.edge), entry=_label("side", head.edge))})
    verdict: Literal["good", "suspect"] = "suspect" if found else "good"
    return HandoffReport(verdict, _label("verdict", verdict), found, describe(tail, "tail"), describe(head, "head"))


def planned_from(previous: Mapping[str, Any], current: Mapping[str, Any]) -> Planned:
    """What the stage-4 shots say about the cut from ``previous`` into ``current``."""
    turned = str((prompt_data.value("shot_transitions", "patterns") or {}).get("turned") or "")
    cast_a = {str(name) for name in previous.get("characters") or [] if str(name).strip()}
    cast_b = {str(name) for name in current.get("characters") or [] if str(name).strip()}
    cut = current.get("cut_in") if isinstance(current.get("cut_in"), Mapping) else {}
    text = f"{previous.get('desc') or ''} {current.get('desc') or ''}"
    settles, held = str(prompt_data.value(_DATA, "settles")), str(prompt_data.value(_DATA, "opens_held"))
    camera_before = f"{previous.get('motion') or ''} {previous.get('camera_movement') or ''} {previous.get('continuity_out') or ''}"
    camera_after = f"{current.get('motion') or ''} {current.get('camera_movement') or ''}"
    return Planned(
        same_scene=str(previous.get("scene_id") or "") == str(current.get("scene_id") or ""),
        shared_subject=bool(cast_a & cast_b) if cast_a and cast_b else True,
        motion_join=str(cut.get("motion_join") or ""),
        turns=bool(turned and re.search(turned, text)),
        ends_settled=bool(re.search(settles, camera_before)),
        opens_held=bool(re.search(held, camera_after)),
        optical=str(cut.get("kind") or "") in {"dissolve", "fade"},
    )


__all__ = ["HandoffError", "HandoffReport", "Planned", "Profile", "compare", "describe", "frames", "measure", "planned_from", "profile"]
