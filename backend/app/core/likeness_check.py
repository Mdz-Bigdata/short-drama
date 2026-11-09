# -*- coding: utf-8 -*-
"""分镜里的真人演员像不像本人：本人正脸照和这一格并排拼成一张，交给看得见图的文本模型打分。

分数低于门槛就带着它说的差别重画一次，两张里留分高的那张。没有看图模型、读不到图或答不清时不拦出图，
只是这一格记成「没核对」。门槛和措辞在 app/data/prompt/real_person.json。
"""

from __future__ import annotations

import base64
import io
import json
import re
from collections.abc import Callable
from typing import Any

from PIL import Image

from app.core import prompt_data
from app.core.real_person import say

_WORDING = "real_person"
_SIDE = 768


def _image(content: bytes) -> Image.Image:
    with Image.open(io.BytesIO(content)) as opened:
        image = opened.convert("RGB")
    image.thumbnail((_SIDE * 2, _SIDE))
    return image


def side_by_side(photo: bytes, panel: bytes) -> str:
    """左边本人照片、右边这一格，白底拼成一张 JPEG data URI。"""
    left, right = _image(photo), _image(panel)
    height = max(left.height, right.height)
    board = Image.new("RGB", (left.width + right.width + 24, height), (255, 255, 255))
    board.paste(left, (0, (height - left.height) // 2))
    board.paste(right, (left.width + 24, (height - right.height) // 2))
    buffer = io.BytesIO()
    board.save(buffer, format="JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def data_uri_bytes(uri: str) -> bytes | None:
    match = re.match(r"^data:[^;,]+;base64,(.*)$", str(uri or ""), re.S)
    return base64.b64decode(match.group(1)) if match else None


def parse(answer: str | None) -> dict[str, Any] | None:
    """``{score, same_person, differences}``；读不出分数就返回 None，当作没核对。"""
    match = re.search(r"\{.*\}", str(answer or ""), re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return None
    try:
        score = float(data.get("score"))
    except (TypeError, ValueError):
        return None
    differences = [str(item).strip().rstrip("。；;.") for item in data.get("differences") or [] if str(item).strip()][:5]
    return {"score": max(0.0, min(10.0, score)), "same_person": bool(data.get("same_person")), "differences": differences}


def threshold() -> float:
    return float(prompt_data.value(_WORDING, "likeness_min_score"))


def passed(check: dict[str, Any] | None) -> bool:
    return check is None or (check["same_person"] and check["score"] >= threshold())


def check(
    describe: Callable[[str, str, str], tuple[str | None, str]], name: str, photo: bytes, panel: bytes,
) -> dict[str, Any] | None:
    """一名真人演员在这一格里像不像本人。``describe(system, prompt, image)`` 是看图模型。"""
    answer, used = describe(say("likeness_system"), say("likeness_prompt", name), side_by_side(photo, panel))
    if not used:
        return None
    result = parse(answer)
    return {**result, "name": name, "model": used} if result else None


def fix_prompt(results: list[dict[str, Any]]) -> str:
    """重画时补在提示词后面：哪个人哪里不像。"""
    parts = [f"「{item['name']}」" + ("：" + "；".join(item["differences"]) if item.get("differences") else "") for item in results]
    return say("likeness_fix", "，".join(parts))


__all__ = ["check", "data_uri_bytes", "fix_prompt", "parse", "passed", "side_by_side", "threshold"]
