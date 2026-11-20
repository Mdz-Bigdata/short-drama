"""第 5 阶段每段视频(一张分镜看板)最近一次没出片的原因，记在任务上给视觉工作区看。

供应商拒单(MiniMax 1026 input image sensitive、Ark InputImageSensitiveContentDetected)以前只出现在阶段报错
和生成队列里，镜头列表上只显示「未生成」。这里按看板记下供应商原话、错误码、分类和这一次实际发出去的图，
看板之后出了片就清掉。只记录，不重试、不换模型、不丢参考。
"""

from __future__ import annotations

import re
import time
from typing import Any, Iterable
from app.core import prompt_data


_WORDING_FILE = "video_failures"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/video_failures.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)

FAILURES_KEY = "5_failures"

INPUT_IMAGE_SENSITIVE = "input_image_sensitive"
PROVIDER_ERROR = "provider_error"

# 供应商原话最多留这么长：够看清错误码与说明，不把整段响应塞进任务。
_MESSAGE_LIMIT = 600
_ARK_SENSITIVE = re.compile(r"InputImageSensitiveContentDetected(?:\.[A-Za-z]+)?")
_ARK_CODE = re.compile(r"HTTP \d{3} ([A-Z][A-Za-z]+(?:\.[A-Za-z]+)?)")
_MINIMAX_CODE = re.compile(r"(?<![\w.])(\d{4})(?![\w.])")


def classify(message: str) -> tuple[str, str]:
    """(kind, code)：供应商判某张输入图敏感的归 input_image_sensitive，其余都是 provider_error。"""
    text = str(message or "")
    lowered = text.lower()
    ark = _ARK_SENSITIVE.search(text)
    if ark:
        return INPUT_IMAGE_SENSITIVE, ark.group(0)
    code = ""
    ark_code = _ARK_CODE.search(text)
    if ark_code:
        code = ark_code.group(1)
    elif "minimax" in lowered or "status=failed" in lowered or "base_resp" in lowered:
        found = _MINIMAX_CODE.search(text)
        code = found.group(1) if found else ""
    if code == "1026" and ("image" in lowered or _text_of("classify.text") in text) and ("sensitive" in lowered or _text_of("classify.text.2") in text):
        return INPUT_IMAGE_SENSITIVE, code
    if "input image sensitive" in lowered or _text_of("classify.text.3") in text or _text_of("classify.text.4") in text:
        return INPUT_IMAGE_SENSITIVE, code
    return PROVIDER_ERROR, code


def sent_images(decision: Any) -> list[str]:
    """一次请求实际发出去的图(首帧、尾帧、参考图)；内联的 data: 图不存进任务。"""
    if not isinstance(decision, dict):
        return []
    urls = [decision.get("first_frame"), decision.get("last_frame"), *(decision.get("reference_images") or [])]
    return list(dict.fromkeys(str(url) for url in urls if isinstance(url, str) and url and not url.startswith("data:")))


def inline_count(decision: Any) -> int:
    """发出去的图里有几张是内联字节(私有资产库的身份视图之类)，只记个数。"""
    if not isinstance(decision, dict):
        return 0
    urls = [decision.get("first_frame"), decision.get("last_frame"), *(decision.get("reference_images") or [])]
    return sum(1 for url in urls if isinstance(url, str) and url.startswith("data:"))


def build(
    *,
    scene_id: str,
    shot_uids: Iterable[int],
    message: str,
    frames: Iterable[str],
    inputs: Iterable[str],
    inline_inputs: int = 0,
    retried_without_frames: bool = False,
    retried_with_stand_ins: bool = False,
    at: float | None = None,
) -> dict:
    """一条失败记录。``frames`` 是本看板发出去的分镜画面，``inputs`` 是这次请求发出去的全部图。"""
    kind, code = classify(message)
    return {
        "scene_id": str(scene_id or ""),
        "shot_uids": [int(uid) for uid in shot_uids if int(uid or 0)],
        "message": str(message or "")[:_MESSAGE_LIMIT],
        "code": code,
        "kind": kind,
        "frames": list(dict.fromkeys(str(url) for url in frames if url)),
        "inputs": list(dict.fromkeys(str(url) for url in inputs if url)),
        "inline_inputs": int(inline_inputs or 0),
        "retried_without_frames": bool(retried_without_frames),
        "retried_with_stand_ins": bool(retried_with_stand_ins),
        "at": float(at if at is not None else time.time()),
    }


def _records(task: dict) -> dict:
    assets = task.setdefault("assets", {})
    records = assets.get(FAILURES_KEY)
    if not isinstance(records, dict):
        records = assets[FAILURES_KEY] = {}
    return records


def record(task: dict, key: int, entry: dict) -> dict:
    """记下(或覆盖)一张看板的失败；先清掉与它镜头重叠的旧记录(重新切段后键可能变了)。"""
    clear(task, entry.get("shot_uids") or [key])
    _records(task)[str(int(key))] = entry
    return task


def clear(task: dict, shot_uids: Iterable[int]) -> dict:
    """这些镜头出片了：凡是覆盖其中任一镜的失败记录都删掉。"""
    uids = {int(uid) for uid in shot_uids if int(uid or 0)}
    if not uids:
        return task
    assets = task.get("assets") if isinstance(task.get("assets"), dict) else {}
    records = assets.get(FAILURES_KEY)
    if not isinstance(records, dict):
        return task
    for key in [key for key, entry in records.items() if _covers(key, entry, uids)]:
        records.pop(key, None)
    return task


def _covers(key: str, entry: Any, uids: set[int]) -> bool:
    covered = {int(uid) for uid in ((entry or {}).get("shot_uids") or []) if isinstance(uid, int)} if isinstance(entry, dict) else set()
    if str(key).isdigit():
        covered.add(int(key))
    return bool(covered & uids)


def by_shot(assets: dict) -> dict[int, dict]:
    """镜头编号 → 覆盖它的那条失败记录。"""
    records = assets.get(FAILURES_KEY) if isinstance(assets, dict) else None
    found: dict[int, dict] = {}
    for key, entry in (records or {}).items() if isinstance(records, dict) else ():
        if not isinstance(entry, dict):
            continue
        uids = [int(uid) for uid in (entry.get("shot_uids") or []) if isinstance(uid, int)]
        if not uids and str(key).isdigit():
            uids = [int(key)]
        for uid in uids:
            found[uid] = entry
    return found


KIND_LABELS = {
    INPUT_IMAGE_SENSITIVE: _text_of("module.kind_labels"),
    PROVIDER_ERROR: _text_of("module.kind_labels.2"),
}


def hint(entry: dict) -> str:
    """给人看的下一步。"""
    scene = str(entry.get("scene_id") or _text_of("hint.scene"))
    if entry.get("kind") == INPUT_IMAGE_SENSITIVE:
        if entry.get("retried_with_stand_ins") and entry.get("retried_without_frames"):
            return (
                _text_of("hint.text").format(scene)
            )
        if entry.get("retried_without_frames"):
            return (
                _text_of("hint.text.2").format(scene)
            )
        return (
            _text_of("hint.text.3").format(scene)
        )
    # 判成版权问题的(Seedance 的 OutputVideoCopyright 一类)：改的是提示词里像现成作品的说法，不是参考图。
    if any(marker.lower() in str(entry.get("message") or "").lower() for marker in _words_of("copyright_markers")):
        return _text_of("hint.copyright")
    return _text_of("hint.text.4")
