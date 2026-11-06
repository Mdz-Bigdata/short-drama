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

#: kind → 剧本拆解目录(``production_assets``)里的键。
CATALOG_KEYS: dict[str, str] = {
    "extra": "extras", "vehicle": "vehicles", "stunt": "stunts", "set_dressing": "set_dressing", "makeup": "makeup",
}
KINDS: tuple[str, ...] = tuple(CATALOG_KEYS)
FILED_KINDS: tuple[str, ...] = tuple(kind for kind in KINDS if kind != "makeup")
LABELS: dict[str, str] = {"extra": "群演", "vehicle": "车辆", "stunt": "特技", "set_dressing": "置景", "makeup": "化妆"}
#: 拍摄稿里给这几类留的小节标题，提取器按它找。
SECTION_LABELS: dict[str, tuple[str, ...]] = {
    "extra": ("群演", "群众演员", "路人", "背景人物"),
    "vehicle": ("车辆", "载具", "画面车辆"),
    "stunt": ("特技", "动作特技", "武打设计", "特技动作"),
    "set_dressing": ("置景", "陈设", "布景", "场景陈设"),
    "makeup": ("化妆", "妆效", "特效化妆", "妆容"),
}
#: 分镜图提示词里的叫法。
PICTURE_NOUN: dict[str, str] = {"extra": "群演参考图", "vehicle": "车辆图", "stunt": "特技参考图", "set_dressing": "置景图", "makeup": "妆效图"}
ONLY_GIVES: dict[str, str] = {
    "extra": "群演参考图只提供人群的服装、体型和疏密，不提供脸和主要人物",
    "vehicle": "车辆图只提供车型、颜色与新旧，不提供人物和背景",
    "stunt": "特技参考图只提供动作的姿态与接触点，不提供人物长相",
    "set_dressing": "置景图只提供陈设的摆放、材质与颜色，不提供人物和光线",
    "makeup": "妆效图只提供伤口、血迹、假体的位置与形态，不提供脸型和五官",
}
#: 写剧本时让模型登记这几类的规则，接在原来五类的规则后面。
WRITER_RULES: str = (
    "- 群演（extras）：没有台词的背景人物，按职能登记（「码头苦力」「宫女若干」），写人数、服装和在做什么；"
    "有台词或反复推动剧情的是角色，不登记在这里。\n"
    "- 车辆（vehicles）：入画的车、船、马车、摩托；写车型、颜色、新旧和谁在用。不开动的大船、飞机算场景。\n"
    "- 特技（stunts）：有风险的动作过程，整体登记一条（「主角撞破窗户」「坠马」），写谁做、在哪、结果；不拆成替身和道具。\n"
    "- 置景（set_dressing）：让场地像那么回事、角色不去碰的陈设：家具、灯具、匾额、帷幔；角色会碰、会用的归道具。\n"
    "- 化妆（makeup）：只登记特殊的：伤口、血迹、假体、老年妆、易容；写在谁脸上或身上、什么形态、哪几集带着（写「第9集起」或「第9-12集」，它决定定妆图画在哪身戏服上）。日常妆不登记。"
)
#: 剧本拆解目录的 JSON 形状，一类一行。
CATALOG_SHAPES: dict[str, str] = {
    "extras": '"extras": [{"name": "群演职能名", "description": "人数、服装、动作和出现的场次"}]',
    "vehicles": '"vehicles": [{"name": "具体车辆名", "description": "车型、颜色、新旧、谁在用和出现的场次"}]',
    "stunts": '"stunts": [{"name": "特技动作名", "description": "谁做、在哪、过程和结果"}]',
    "set_dressing": '"set_dressing": [{"name": "陈设名", "description": "摆在哪、材质、颜色和出现的场次"}]',
    "makeup": '"makeup": [{"name": "角色名·妆效名", "description": "位置、形态、颜色和哪几集带着（第9集起 / 第9-12集）"}]',
}


def reference_note(number: int, kind: str, name: str) -> str:
    """参考图N 只锁一件这类资产的那句话；句中不带「；」「。」。"""
    label = LABELS.get(kind, kind)
    if kind == "extra":
        return f"参考图{number}仅锁定{label}「{name}」的服装、体型与人群疏密，不采用图中面孔、背景与主要人物，不是额外剧情"
    if kind == "makeup":
        return f"参考图{number}仅锁定{label}「{name}」的位置、形态与颜色，不采用图中脸型、五官与背景，不是额外人物"
    if kind == "stunt":
        return f"参考图{number}仅锁定{label}「{name}」的动作姿态与接触点，不采用图中人物长相与背景，不是额外剧情"
    return f"参考图{number}仅锁定{label}「{name}」的外形、材质与颜色，不采用图中背景与人物，不是额外剧情或额外人物"


__all__ = [
    "CATALOG_KEYS", "CATALOG_SHAPES", "FILED_KINDS", "KINDS", "LABELS", "ONLY_GIVES", "PICTURE_NOUN", "SECTION_LABELS", "WRITER_RULES", "reference_note",
]
