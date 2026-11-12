# -*- coding: utf-8 -*-
"""拆解时比原来五类资产多出来的几类：群演、车辆、特技、置景、化妆。

分类和判断规则按 StudioBinder 的拆解元素表(docs/screenplay-standard/剧本规范与拆解元素.md 第 6 节)：
道具是角色会碰的东西，置景是不碰的；现场特效归特效，特技是一个过程不是一个人；群演没有台词；
化妆只记假体、伤口、血这类特殊的。这几类都是"有参考图更好、没有也能拍"的：分镜前的就绪检查只
报数，不拦。

这里是唯一的清单；资产库、分镜绑定、剧本提取和写剧本时的资产目录都从这里取名字。
化妆只留清单不入库：妆效画在角色的定妆图上(见 ``character_looks``)，资产库里的化妆条目是旧项目留下的。
"""

from __future__ import annotations
from app.core import prompt_data


_WORDING_FILE = "breakdown_kinds"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/breakdown_kinds.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)

#: kind → 剧本拆解目录(``production_assets``)里的键。
CATALOG_KEYS: dict[str, str] = {
    "extra": "extras", "vehicle": "vehicles", "stunt": "stunts", "set_dressing": "set_dressing", "makeup": "makeup",
}
KINDS: tuple[str, ...] = tuple(CATALOG_KEYS)
FILED_KINDS: tuple[str, ...] = tuple(kind for kind in KINDS if kind != "makeup")
LABELS: dict[str, str] = {"extra": _text_of("module.labels.extra"), "vehicle": _text_of("module.labels.vehicle"), "stunt": _text_of("module.labels.stunt"), "set_dressing": _text_of("module.labels.set_dressing"), "makeup": _text_of("module.labels.makeup")}
#: 拍摄稿里给这几类留的小节标题，提取器按它找。
SECTION_LABELS: dict[str, tuple[str, ...]] = {
    "extra": _words_of("module.section_labels.extra"),
    "vehicle": _words_of("module.section_labels.vehicle"),
    "stunt": _words_of("module.section_labels.stunt"),
    "set_dressing": _words_of("module.section_labels.set_dressing"),
    "makeup": _words_of("module.section_labels.makeup"),
}
#: 分镜图提示词里的叫法。
PICTURE_NOUN: dict[str, str] = {"extra": _text_of("module.picture_noun.extra"), "vehicle": _text_of("module.picture_noun.vehicle"), "stunt": _text_of("module.picture_noun.stunt"), "set_dressing": _text_of("module.picture_noun.set_dressing"), "makeup": _text_of("module.picture_noun.makeup")}
ONLY_GIVES: dict[str, str] = {
    "extra": _text_of("module.only_gives.extra"),
    "vehicle": _text_of("module.only_gives.vehicle"),
    "stunt": _text_of("module.only_gives.stunt"),
    "set_dressing": _text_of("module.only_gives.set_dressing"),
    "makeup": _text_of("module.only_gives.makeup"),
}
#: 写剧本时让模型登记这几类的规则，接在原来五类的规则后面。
WRITER_RULES: str = (
    _text_of("module.writer_rules")
)
#: 剧本拆解目录的 JSON 形状，一类一行。
CATALOG_SHAPES: dict[str, str] = {
    "extras": _text_of("module.catalog_shapes.extras"),
    "vehicles": _text_of("module.catalog_shapes.vehicles"),
    "stunts": _text_of("module.catalog_shapes.stunts"),
    "set_dressing": _text_of("module.catalog_shapes.set_dressing"),
    "makeup": _text_of("module.catalog_shapes.makeup"),
}


def reference_note(number: int, kind: str, name: str) -> str:
    """参考图N 只锁一件这类资产的那句话；句中不带「；」「。」。"""
    label = LABELS.get(kind, kind)
    if kind == "extra":
        return _text_of("reference_note.text").format(number, label, name)
    if kind == "makeup":
        return _text_of("reference_note.text.2").format(number, label, name)
    if kind == "stunt":
        return _text_of("reference_note.text.3").format(number, label, name)
    return _text_of("reference_note.text.4").format(number, label, name)


__all__ = [
    "CATALOG_KEYS", "CATALOG_SHAPES", "FILED_KINDS", "KINDS", "LABELS", "ONLY_GIVES", "PICTURE_NOUN", "SECTION_LABELS", "WRITER_RULES", "reference_note",
]
