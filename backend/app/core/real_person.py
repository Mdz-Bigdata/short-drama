# -*- coding: utf-8 -*-
"""真人演员：演员本人的照片就是这个角色的身份，按照片出分镜和视频，尽量像本人。

元素库里的数字演员(kind actor)在 ``metadata["real_person"]`` 记一条真人记录：

- ``person`` 照片上的人、``scope`` 授权用途、``expires`` 授权到哪天，``confirmed_by`` / ``confirmed_at``
  是哪个账号在什么时候确认持有肖像授权。没有这条确认，就不算真人演员。
- ``ark_assets`` 是这个人在火山方舟「真人人像库」里通过本人认证入库的素材(``asset://asset-…``)。Seedance 2.0 / 2.5
  不接受直接上传的真人脸，只认这种素材；其他视频模型直接用照片。

照片放在身份视图槽位里：``face_front`` 正脸特写必填，``front`` 全身最好有，其余可选。真人演员不重新生成设定集，
重新生成和项目同步都不能把照片换掉。
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, datetime, timezone
from typing import Any

from app.core import prompt_data

KEY = "real_person"
FACE_SLOT = "face_front"
BODY_SLOT = "front"
# 照片缺哪个身份视图，就拿正脸或全身顶上：设定集要五个锚点，真人演员不为凑数去画。
FACE_VIEWS = ("face_front", "face_three_quarter")
BODY_VIEWS = ("front", "profile", "back")
_ASSET = re.compile(r"^asset://[A-Za-z0-9][A-Za-z0-9_-]{2,127}$")
MAX_ASSETS = 9
_WORDING = "real_person"


class RealPersonError(ValueError):
    pass


def record_of(metadata: Mapping[str, Any] | None) -> dict[str, Any] | None:
    raw = (metadata or {}).get(KEY) if isinstance(metadata, Mapping) else None
    return raw if isinstance(raw, dict) and raw.get("confirmed_by") else None


def is_real_person(metadata: Mapping[str, Any] | None) -> bool:
    return record_of(metadata) is not None


def expired(record: Mapping[str, Any] | None, today: date | None = None) -> bool:
    """授权过了期：照片不再拿去生成。"""
    text = str((record or {}).get("expires") or "").strip()
    if not text:
        return False
    try:
        return date.fromisoformat(text) < (today or date.today())
    except ValueError:
        return False


def usable(metadata: Mapping[str, Any] | None) -> bool:
    record = record_of(metadata)
    return record is not None and not expired(record)


def ark_assets(metadata: Mapping[str, Any] | None) -> list[str]:
    record = record_of(metadata) or {}
    return [str(item) for item in record.get("ark_assets") or [] if _ASSET.match(str(item))]


def clean_record(
    *, person: str, scope: str, expires: str, ark_assets: list[str] | None, confirmed: bool, confirmed_by: str,
) -> dict[str, Any]:
    """校验后的真人记录；没确认授权、日期写错、素材 ID 不是 asset:// 都拒绝。"""
    if not confirmed:
        raise RealPersonError("请先确认已取得照片中本人的肖像使用授权")
    person = str(person or "").strip()[:60]
    if not person:
        raise RealPersonError("请填写照片上是谁")
    expires = str(expires or "").strip()
    if expires:
        try:
            date.fromisoformat(expires)
        except ValueError as exc:
            raise RealPersonError("授权有效期请写成 2027-12-31 这样的日期") from exc
    assets = [str(item).strip() for item in ark_assets or [] if str(item).strip()]
    bad = [item for item in assets if not _ASSET.match(item)]
    if bad:
        raise RealPersonError(f"火山方舟真人素材 ID 应是 asset://asset-… 的形式：{bad[0]}")
    if len(assets) > MAX_ASSETS:
        raise RealPersonError(f"一名演员最多登记 {MAX_ASSETS} 个真人素材")
    return {
        "person": person, "scope": str(scope or "").strip()[:200], "expires": expires,
        "ark_assets": list(dict.fromkeys(assets)), "confirmed_by": str(confirmed_by),
        "confirmed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def actor_ready(slots: set[str]) -> bool:
    """真人演员有正脸特写就能用。"""
    return FACE_SLOT in slots


def view_slots(slots: set[str]) -> dict[str, str]:
    """五个身份锚点各用哪张照片：有就用自己的槽位，没有就拿正脸或全身顶上。"""
    face = FACE_SLOT if FACE_SLOT in slots else BODY_SLOT
    body = BODY_SLOT if BODY_SLOT in slots else FACE_SLOT
    return {view: view if view in slots else (face if view in FACE_VIEWS else body) for view in (*BODY_VIEWS, *FACE_VIEWS)}


def keep_likeness(negative: str) -> str:
    """去掉负面词里「别像真人、别像证件照」那几样：画真人演员时它们正好和照片对着干。"""
    text = str(negative or "")
    for phrase in prompt_data.words(_WORDING, "drop_negatives"):
        text = text.replace(phrase, "")
    # 删词后留下的连续分隔符收成一个；「避免：」后面空了就整段去掉。
    text = re.sub(r"(?:[、/，,]\s*){2,}", "、", text)
    text = re.sub(r"避免：\s*[、/，,]?\s*；", "", text)
    text = re.sub(r"避免：\s*[、/，,]\s*", "避免：", text)
    text = re.sub(r"[、/，,]\s*；", "；", text)
    text = re.sub(r"([(（])\s*并", r"\1", text)
    return re.sub(r"[(（]\s*[)）]", "", text)


def names_in(references: list[dict]) -> list[str]:
    """这批参考里有哪些真人演员。"""
    return list(dict.fromkeys(str(item.get("name") or "") for item in references if item.get("real_person")))


def for_seedance(references: list[dict], *, per_person: int = 3) -> tuple[list[dict], list[str]]:
    """Seedance 只认火山方舟真人人像库的素材：真人演员的照片和定妆图(上面都有真人脸)换成他的 asset:// 素材。

    返回 (新的参考列表, 没登记素材的真人演员)。没登记的这一镜只靠文字描述，照片不发，免得整条被拒。
    定妆图的造型名和妆效跟着第一张素材走，服装改由文字说。
    """
    out: list[dict] = []
    missing: list[str] = []
    done: set[str] = set()
    for item in references:
        if not item.get("real_person"):
            out.append(item)
            continue
        name = str(item.get("name") or "")
        if name in done:
            continue
        done.add(name)
        group = [entry for entry in references if entry.get("real_person") and str(entry.get("name") or "") == name]
        main = next((entry for entry in group if entry.get("view") != "face"), group[0])
        assets = list(dict.fromkeys(asset for entry in group for asset in entry.get("ark_assets") or []))[:per_person]
        if not assets:
            missing.append(name)
            continue
        for index, asset in enumerate(assets):
            out.append({
                "kind": "actor", "name": name, "image_url": asset, "real_person": True, "view": "face", "ark_asset": True,
                **({key: main[key] for key in ("variant", "look_makeup", "outfit") if main.get(key)} if index == 0 else {}),
            })
    return out, missing


def say(key: str, *args: object) -> str:
    text = prompt_data.text(_WORDING, key)
    return text.format(*args) if args else text


__all__ = [
    "BODY_SLOT", "FACE_SLOT", "KEY", "MAX_ASSETS", "RealPersonError", "actor_ready", "ark_assets", "clean_record",
    "expired", "for_seedance", "is_real_person", "keep_likeness", "names_in", "record_of", "say", "usable", "view_slots",
]
