# -*- coding: utf-8 -*-
"""真人审核拦截时的彩色替身：分镜画面里的人换成彩色影子，长相只认定妆照。

Seedance(Ark) 把分镜帧里的写实人脸判成「疑似真人」拒单时，第 5 阶段先让出图模型把分镜帧里的每个人
重画成一整块纯色影子(构图、站位、姿势、朝向、场景不变)，再把影子帧当站位参考、每人一张定妆照当长相参考，
配一段很短的提示词重发：白色是男主角、蓝色是女主角、黄色是反派或群演。画面里没有真人，审核拦不住；
脸只来自定妆照(配了可信素材库授权素材时就是那张备案的正脸)，不会被分镜帧上画偏的脸带跑。

认影子靠颜色加一句身份：「白色影子是男主角沈砚（男，青色长衫）」。出图模型照这句话认出分镜帧里谁是谁，
视频模型照同一句话把影子换回人。颜色按整部剧的演员表定，同一个人在每一镜都是同一种颜色。

颜色表、句子和长度上限都在 ``app/data/prompt/color_stand_ins.json``。
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.core import prompt_data

_DATA = "color_stand_ins"

# (名字, 角色描述, 角色位)：与 drama_service.project_roster 的元组一致。
Person = tuple[str, str, str]


def _text(key: str) -> str:
    return prompt_data.text(_DATA, key)


def _words(key: str) -> tuple[str, ...]:
    return prompt_data.words(_DATA, key)


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text or "").split()).strip("，。；、 ")
    return text if len(text) <= limit else text[:limit].rstrip("，。；、 ") + "…"


@dataclass(frozen=True)
class Figure:
    """分镜帧里的一个影子：谁、什么颜色、怎么认。"""

    name: str
    color: str
    label: str
    gender: str = ""
    clothing: str = ""

    def line(self) -> str:
        traits = "，".join(part for part in (self.gender, self.clothing) if part)
        text = _text("figure").format(color=self.color, label=self.label, name=self.name, traits=traits)
        return text if traits else text.replace("（）", "")


def clothing_from_description(description: str) -> str:
    """角色设定里第一句写衣服的话（「洗旧麻灰短褐」）；设定没写衣服时返回空串。"""
    garments = _words("garment_words")
    for fragment in re.split(r"[；;。，,、\n]", str(description or "")):
        fragment = fragment.strip()
        if fragment and any(word in fragment for word in garments):
            return fragment
    return ""


def palette(roster: Sequence[Person], genders: Mapping[str, str]) -> dict[str, tuple[str, str]]:
    """整部剧每个有名有姓的人用什么颜色：名字 → (颜色, 身份)。男主白、女主蓝、头号反派黄，其余按演员表依次取色。"""
    lead_words, opponent_words = _words("lead_words"), _words("opponent_words")
    male_words, female_words = _words("male_lead_words"), _words("female_lead_words")
    people = [(str(name).strip(), str(role or "")) for name, _desc, role in roster if str(name or "").strip()]
    leads = [(name, role) for name, role in people if any(word in role for word in lead_words)]

    def lead(own_words: tuple[str, ...], other_words: tuple[str, ...], gender: str) -> str | None:
        named = next((name for name, role in leads if any(word in role for word in own_words)), None)
        if named:
            return named
        return next((
            name for name, role in leads
            if genders.get(name) == gender and not any(word in role for word in other_words)
        ), None)

    colors: dict[str, tuple[str, str]] = {}
    male = lead(male_words, female_words, "male")
    if male:
        colors[male] = tuple(_words("male_lead"))  # type: ignore[assignment]
    female = lead(female_words, male_words, "female")
    if female and female not in colors:
        colors[female] = tuple(_words("female_lead"))  # type: ignore[assignment]
    opponent = next((name for name, role in people if name not in colors and any(word in role for word in opponent_words)), None)
    if opponent:
        colors[opponent] = tuple(_words("opponent"))  # type: ignore[assignment]
    others = _words("others")
    rest = [name for name, _role in people if name not in colors]
    for index, name in enumerate(dict.fromkeys(rest)):
        colors[name] = (others[index % len(others)], _text("other_label"))
    return colors


def figures(
    in_shot: Sequence[Person],
    roster: Sequence[Person],
    genders: Mapping[str, str],
    clothing: Mapping[str, str],
) -> list[Figure]:
    """本镜入镜的每个人一个影子；同一镜里颜色不重复。"""
    colors = palette(roster, genders)
    gender_words = prompt_data.value(_DATA, "gender_words")
    limit = prompt_data.number(_DATA, "max_clothing_chars")
    used: set[str] = set()
    out: list[Figure] = []
    for name, _desc, _role in in_shot:
        name = str(name or "").strip()
        if not name or any(figure.name == name for figure in out):
            continue
        color, label = colors.get(name, ("", _text("other_label")))
        if not color or color in used:
            color = next((c for c in _words("others") if c not in used and c not in {_text("crowd")}), "")
        if not color:
            continue
        used.add(color)
        out.append(Figure(
            name=name, color=color, label=label,
            gender=str(gender_words.get(genders.get(name, ""), "")),
            clothing=_clip(clothing.get(name, ""), limit),
        ))
    return out


def crowd_color(shot_figures: Sequence[Figure]) -> str:
    """群演的颜色：黄色；黄色已经给了本镜的反派时换灰色，免得认错人。"""
    taken = {figure.color for figure in shot_figures}
    return _text("crowd") if _text("crowd") not in taken else _text("crowd_when_taken")


def has_crowd(desc: str, characters: object, cast_names: Sequence[str]) -> bool:
    """本镜有没有群演：分镜描述里写了路人、围观之类，或入镜名单里有演员表外的人。"""
    if any(word in str(desc or "") for word in _words("crowd_words")):
        return True
    named = characters if isinstance(characters, (list, tuple)) else str(characters or "").replace("，", "、").split("、")
    cast = {str(name).strip() for name in cast_names}
    return any(str(name).strip() and str(name).strip() not in cast for name in named)


def max_frames() -> int:
    """一次最多重画几张分镜帧：每张都是一次出图调用。"""
    return prompt_data.number(_DATA, "max_frames")


def legend(shot_figures: Sequence[Figure], crowd: bool = False) -> str:
    """「白色影子是男主角沈砚（男，青色长衫）；蓝色影子是……；其余黄色影子是群演」。"""
    lines = [figure.line() for figure in shot_figures]
    if crowd:
        lines.append(_text("crowd_line").format(color=crowd_color(shot_figures)))
    return _text("legend_joiner").join(lines)


def repaint_prompt(shot_figures: Sequence[Figure], crowd: bool = False) -> str:
    """给出图模型：把这张分镜帧里的人重画成彩色影子，别的都不动。"""
    return _text("repaint").format(legend=legend(shot_figures, crowd))


@dataclass(frozen=True)
class StandInReferences:
    """影子重发这一次带的图，按发送顺序；参考图 N 就是 images[N-1]。"""

    images: list[str]
    frame_count: int
    face_numbers: dict[str, int]
    scene_number: int | None


def references(
    frames: Sequence[str],
    faces: Mapping[str, str],
    scene: str | None = None,
    *,
    limit: int = 9,
) -> StandInReferences:
    """影子帧在前，每人一张定妆照随后，场地图最后；超出上限先丢场地图，再丢排在后面的定妆照。"""
    frames = list(dict.fromkeys(url for url in frames if url))[: prompt_data.number(_DATA, "max_frames")]
    frames = frames[: max(1, limit - 1)]
    images = list(frames)
    face_numbers: dict[str, int] = {}
    for name, url in faces.items():
        if not url or len(images) >= limit:
            continue
        if url not in images:
            images.append(url)
        face_numbers[name] = images.index(url) + 1
    scene_number = None
    if scene and scene not in images and len(images) < limit:
        images.append(scene)
        scene_number = len(images)
    return StandInReferences(images=images, frame_count=len(frames), face_numbers=face_numbers, scene_number=scene_number)


def clip_prompt(
    shot_figures: Sequence[Figure],
    refs: StandInReferences,
    *,
    action: str = "",
    dialogue: str = "",
    crowd: bool = False,
) -> str:
    """影子重发用的短提示词：谁是哪个颜色、长相认哪张定妆照、这一镜演什么、说什么。"""
    frames = "、".join(str(number) for number in range(1, refs.frame_count + 1))
    faces = [
        _text("face").format(name=figure.name, number=refs.face_numbers[figure.name])
        for figure in shot_figures if figure.name in refs.face_numbers
    ]
    if refs.scene_number:
        faces.append(_text("scene").format(number=refs.scene_number))
    action = _clip(action, prompt_data.number(_DATA, "max_action_chars"))
    dialogue = _clip(dialogue, prompt_data.number(_DATA, "max_dialogue_chars"))
    text = _text("clip").format(
        frames=frames,
        legend=legend(shot_figures, crowd),
        faces=_text("face_joiner").join(faces),
        action=_text("action").format(text=action) if action else "",
        dialogue=_text("dialogue").format(text=dialogue) if dialogue else "",
    )
    return text.replace("。。", "。").strip()


__all__ = [
    "Figure", "StandInReferences", "clip_prompt", "clothing_from_description", "crowd_color", "figures", "has_crowd", "legend", "max_frames", "palette",
    "references", "repaint_prompt",
]
