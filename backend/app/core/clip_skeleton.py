# -*- coding: utf-8 -*-
"""The fixed sentences every clip prompt restates, written for the model that will read them.

《系统实际下发提示词骨架》 lays a clip prompt out as three paragraphs under the literal headers
``Pa1`` / ``Pa2`` / ``Pa3``. Besides what each shot says, it carries sentences that never change:

- **Pa1** — what kind of anchor each reference picture is (锚型定义 + one row per picture),
  which pictures are one person and which are different people, what language the lines are
  spoken in, then the shot sequence under ``2 Conti Movs：``;
- **Pa2** — the fixed space axis; in a fight the camera line and the impact sounds;
- **Pa3** — the performance lock, the round / turn lock, the voice and text bans, and the tail:
  portrait safety, the on-screen text policy and the ban list.

The wording is data (``app/data/prompt/clip_skeleton.json``); this module only decides which
sentence a shot gets. Three dialects: ``seedance`` marks sounds with angle brackets, ``h3``
(MiniMax H3) takes the same content without them and with its own performance wording, and
every other model gets plain Chinese.

Lines of the skeleton this project already writes in its own words (physics over the reference,
contact reaction, the landing lock, form and texture continuity, picture quality, the style
lock, the appearance brief) are not repeated here — see
``docs/prompt-template-full-integration/skeleton-coverage.md`` for the line-by-line map.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from app.core import prompt_data
from app.core.asset_mentions import MENTION, mention

_DATA = "clip_skeleton"

#: 本模块写的分节，都是每条重申的固定句：不计入正文预算。
SECTIONS: tuple[str, ...] = (
    "pa1", "anchor_types", "same_instance", "dialogue_language", "sequence_head", "pa2", "space_axis", "lens", "impact_sound",
    "pa3", "performance_lock", "chain_lock", "voice_ban", "portrait_safety", "text_policy", "ban_list",
    # 结构声明后面的「一段只做一个主要变化」、多瞬间片段最后一块之后的「到达后保持到片尾」：同样是每条重申的固定句，
    # 不计入正文预算(video_prompt_engine / slice_video 写)。
    "one_change", "end_hold",
)
#: 只有一个标题的分节：标题前空一行，标题后紧跟正文。
HEADERS: frozenset[str] = frozenset({"pa1", "pa2", "pa3", "sequence_head"})
#: H3 英文改写不带的分节：标题与禁令。禁令按官方契约在改写里写成正面约束。
NOT_FOR_REWRITE: frozenset[str] = frozenset({"pa1", "pa2", "pa3", "sequence_head", "voice_ban", "portrait_safety", "text_policy", "ban_list"})

SHORT_SECONDS = float(prompt_data.value(_DATA, "performance_lock")["short_seconds"])
_FIXED_CAMERA = prompt_data.pattern(_DATA, "fixed_camera")
_SIGH = re.compile(str(prompt_data.value(_DATA, "performance_lock")["sigh_in_script"]))
_SFX_SPLIT = re.compile(str(prompt_data.value(_DATA, "sfx")["split"]))
_NOT_SFX = re.compile(str(prompt_data.value(_DATA, "sfx")["not_sfx"]), re.I)
_LANGUAGE_LINE = re.compile(str(prompt_data.value(_DATA, "dialogue_language")["parse"]))


def _data(key: str):
    return prompt_data.value(_DATA, key)


def _unique(items: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(str(item).strip() for item in items if str(item).strip()))


def family(model: str) -> str:
    """``seedance`` / ``h3`` / ``plain``：这条提示词按哪种写法写。"""
    from app.core.video_references import normalize_video_provider

    return {"seedance": "seedance", "minimax_h3": "h3"}.get(normalize_video_provider(str(model or "")).family, "plain")


def headers() -> dict[str, str]:
    names = _data("headers")
    return {"pa1": names["pa1"], "pa2": names["pa2"], "pa3": names["pa3"], "sequence_head": names["sequence"]}


def _imaged_costumes(costumes: Sequence[tuple[str, str]], costume_images: Sequence[str]) -> list[tuple[str, str]]:
    """有自己一张参考图的服装(旧项目的服装资产)：(穿着者, 服装名)。妆造已经画在人物图上的不算。"""
    imaged = set(_unique(costume_images))
    return list(dict.fromkeys(
        (str(wearer).strip(), str(costume).strip()) for wearer, costume in costumes
        if str(wearer).strip() and str(costume).strip() in imaged
    ))


def _anchor_rows(
    cast: Sequence[str], scenes: Sequence[str], props: Sequence[str],
    costumes: Sequence[tuple[str, str]] = (), costume_images: Sequence[str] = (),
) -> list[tuple[str, str]]:
    kinds = _data("anchor_types")["kinds"]
    pairs = _imaged_costumes(costumes, costume_images)
    dressed_by_picture = {wearer for wearer, _ in pairs}
    # 人物图上的人已经穿着戏服(服装长在人物上)：一张图管脸也管衣服。另有服装图的人，人物图只管脸。
    rows = [(name, kinds["cast_with_costume_image"] if name in dressed_by_picture else kinds["cast"]) for name in _unique(cast)]
    rows += [(costume, kinds["costume"]) for costume in _unique([costume for _, costume in pairs])]
    rows += [(name, kinds["prop"]) for name in _unique(props)]
    rows += [(name, kinds["scene"]) for name in _unique(scenes)]
    return rows


def anchor_types(
    cast: Sequence[str], scenes: Sequence[str], props: Sequence[str],
    costumes: Sequence[tuple[str, str]] = (), costume_images: Sequence[str] = (),
) -> str:
    """锚型定义：本镜用到的每种锚各管什么，再逐张参考图写明它是哪种锚。没有参考图的镜头不写。"""
    rows = _anchor_rows(cast, scenes, props, costumes, costume_images)
    if not rows:
        return ""
    data = _data("anchor_types")
    used = {kind for _, kind in rows}
    lines = [str(data["header"])]
    lines += [str(data["definition"]).format(type=kind, gives=gives) for kind, gives in data["definitions"] if kind in used]
    lines += [str(data["row"]).format(ref=mention(name), type=kind) for name, kind in rows]
    return "\n".join(lines)


def same_instance(
    cast: Sequence[str], costumes: Sequence[tuple[str, str]] = (), costume_images: Sequence[str] = (), *, references: bool = True,
) -> str:
    """哪几张图是同一个人、哪几个人各是各的；参考图上的水印和路人不带进画面。"""
    if not references:
        return ""
    data = _data("same_instance")
    parts = [
        str(data["pair"]).format(person=mention(wearer), costume=mention(costume))
        for wearer, costume in _imaged_costumes(costumes, costume_images)
    ]
    people = _unique(cast)
    if len(people) > 1:
        parts.append(str(data["distinct"]).format(people=str(data["people_joiner"]).join(mention(name) for name in people)))
    if not parts:
        # 只有一个人也写「禁止分身」；画面里没有人的镜头只留水印与路人那半句。
        return str(data["no_clone"]).format(tail=data["tail"]) if people else str(data["tail"])
    return str(data["with_parts"]).format(parts=str(data["joiner"]).join(parts), tail=data["tail"])


def dialogue_language(family_: str, on_screen: Sequence[str], off_screen: Sequence[str] = ()) -> str:
    """对白语言：谁说哪种话；画面里有人开口时口型按这种语言对。只有音画同生的两类模型写。"""
    data = _data("dialogue_language")
    language = data["language"].get(family_)
    if not language:
        return ""
    seen = _unique(on_screen)
    speakers = [mention(name) for name in seen] + [name for name in _unique(off_screen) if name not in seen]
    return str(data["line"]).format(
        speakers="、".join(speakers) or data["unnamed"], language=language, sync=data["sync"] if seen else "",
    )


def space_axis(axis: str, *, fight_pair: bool = False) -> str:
    """空间坐标全程固定：本镜的动作轴线；两人对打时机位留在两人连线的同一侧。"""
    data = _data("space_axis")
    parts = [part for part in (str(axis or "").strip().rstrip("。；;"), str(data["fight_side"]) if fight_pair else "") if part]
    return str(data["line"]).format(axis="；".join(parts)) if parts else ""


def fixed_camera(camera_movement: str) -> bool:
    return bool(_FIXED_CAMERA.search(str(camera_movement or "")))


def close_size(shot_size: str) -> bool:
    """近景、特写一类的景别(CU / MCU / 特写 / 近景…)：脸上的细微反应看得见的景别。"""
    size = str(shot_size or "").upper()
    return any(str(word).upper() in size for word in _data("close_sizes"))


def listener_camera_line() -> str:
    """「表情细微，机位固定或极慢推近」这句本身(片段拼块时据此认出单镜运镜一行里写过它)。"""
    return prompt_data.text(_DATA, "listener_camera")


def listener_camera(shot_size: str, camera_movement: str, *, listening: bool) -> str:
    """听的人的近景反应镜头又在动机位时补一句：表情细微，机位固定或极慢推近——机位不和细微的表演抢。

    运镜本身不改；固定机位、不是近景、或画面里的人自己在说话时不写。
    """
    if not listening or fixed_camera(camera_movement) or not str(camera_movement or "").strip() or not close_size(shot_size):
        return ""
    return listener_camera_line()


def lens(*, fight: bool, camera_movement: str = "") -> str:
    """打戏的运镜一句：镜头跟着动作走。本镜定了固定机位时不写，不和它打架。"""
    return prompt_data.text(_DATA, "lens_fight") if fight and not fixed_camera(camera_movement) else ""


def sfx_marks(text: str) -> str:
    """Seedance 的音效写在尖括号里：按标点拆开，每个声音一对；静默规则和人声不括。"""
    marks = _data("sfx")
    pieces = []
    for piece in _SFX_SPLIT.split(str(text or "")):
        body = piece.strip()
        if not body or _SFX_SPLIT.fullmatch(piece) or body.startswith(marks["open"]) or _NOT_SFX.search(body):
            pieces.append(piece)
        else:
            pieces.append(f"{marks['open']}{body}{marks['close']}")
    return "".join(pieces)


def first_sound_marked(text: str) -> str:
    """一句声音描述只括声音本身(第一个分句)，后面说它在环境里听起来如何的话不括。"""
    head, comma, rest = str(text or "").partition("，")
    return f"{sfx_marks(head)}{comma}{rest}"


def impact_sound(family_: str) -> str:
    return str(_data("impact_sound")[family_])


def performance_lock(family_: str, *, short: bool = False, script: str = "", back: bool = False) -> str:
    """表演锁：脸一直在变、听的人也在演。短片段只留第一句；H3 另加不叹气，剧本自己写了叹气时不加。

    ``back``：背对镜头的镜头看不见脸，不写「面部全程在变」，只写肩背与站姿、不转身。
    """
    data = _data("performance_lock")
    lines = [str(line) for line in data["back" if back else family_]]
    if short and not back:
        lines = lines[:1]
    if family_ == "h3" and not _SIGH.search(str(script or "")):
        lines.append(str(data["no_sigh"]))
    return "\n".join(lines)


def chain_lock(*, fight: bool, camera_fixed: bool = False, turns: int = 0) -> str:
    """回合锁：打戏一招接一招、打到身上、不出本场景、镜头不停；文戏两句以上台词时话轮依次接上。"""
    data = _data("chain_lock")
    if fight:
        return "".join(str(data[key]) for key in ("fight", "impact", "scene", *(() if camera_fixed else ("camera",))))
    return str(data["talk"]) if turns >= 2 else ""


def voice_ban(*, native_audio: bool) -> str:
    lines = ([prompt_data.text(_DATA, "voice_ban")] if native_audio else []) + [prompt_data.text(_DATA, "text_ban")]
    return "\n".join(lines)


def tail(*, people: bool, real_person: bool = False, review_safe: bool = False, dialogue: bool = False) -> dict[str, str]:
    """结尾三段：人物肖像、画面文字、禁止出现。

    真人演员的镜头不写「均为原创虚构角色」，也不禁真人肖像——那正是要拍的人。``review_safe``
    (过审构图：少给正脸近景)默认关：本项目的镜头要看得清脸，过审靠登记过的人像素材。
    """
    portrait = _data("portrait_safety")
    policy = _data("text_policy")
    ban = _data("ban_list")
    fictional = people and not real_person
    items = [
        *ban["always"],
        *([] if real_person else ban["fictional_people"]),
        *(ban["review_safe"] if fictional and review_safe else []),
    ]
    return {
        "portrait_safety": (str(portrait["fiction"]) + (str(portrait["review_safe"]) if review_safe else "")) if fictional else "",
        "text_policy": str(policy["dialogue" if dialogue else "silent"]),
        "ban_list": str(ban["line"]).format(items="、".join(str(item) for item in items)),
    }


def _row_pattern() -> re.Pattern[str]:
    data = _data("anchor_types")
    kinds = "|".join(re.escape(kind) for kind, _ in sorted(data["definitions"], key=lambda item: -len(item[0])))
    return re.compile(str(data["row"]).replace("{ref}", "(?P<ref>.+)").replace("{type}", f"(?P<type>{kinds})") + "$")


def settle(text: str, *, frames_only: bool = False) -> str:
    """参考图定好号之后收拾锚型定义：没随请求发出去的图不留行，用不到的定义与空了的标题一并去掉。

    ``frames_only``：请求里只有首(尾)帧时整段不写，「同一人 / 各是不同的角色」那行也不写——
    提示词不指向不存在的参考图，长相以首帧为准。
    """
    data = _data("anchor_types")
    same = _data("same_instance")
    kinds = data["kinds"]
    row = _row_pattern()
    lines = str(text or "").split("\n")
    tail_ = str(same["tail"])
    pair_end = str(same["pair"]).rsplit("}", 1)[-1]
    dropped: set[int] = set()
    # 「某人、某戏服 为同一人」说的是两张图：戏服图没发出去就不留这半句，这个人的图也就连服装一起管。
    alone: set[str] = set()
    for index, line in enumerate(lines):
        if not line.endswith(tail_):
            continue
        if frames_only:
            dropped.add(index)
            continue
        if pair_end not in line:
            continue
        head = line[: -len(str(same["with_parts"]).format(parts="", tail=tail_))]
        parts = []
        for part in head.split(str(same["joiner"])):
            if part.endswith(pair_end) and part.count("（参考图") < 2:
                alone.add(part.split(str(same["people_joiner"]), 1)[0])
            else:
                parts.append(part)
        lines[index] = (
            str(same["with_parts"]).format(parts=str(same["joiner"]).join(parts), tail=tail_)
            if parts else str(same["no_clone"]).format(tail=tail_)
        )

    kept_kinds: set[str] = set()
    found = False
    for index, line in enumerate(lines):
        matched = row.match(line)
        if not matched:
            continue
        found = True
        ref, kind = matched.group("ref"), matched.group("type")
        if frames_only or "（参考图" not in ref:
            dropped.add(index)
            continue
        if kind == kinds["cast_with_costume_image"] and ref in alone:
            kind = str(kinds["cast"])
            lines[index] = str(data["row"]).format(ref=ref, type=kind)
        kept_kinds.add(kind)
    definitions = {str(data["definition"]).format(type=kind, gives=gives): kind for kind, gives in data["definitions"]}
    for index, line in enumerate(lines):
        if line == data["header"] and (frames_only or (found and not kept_kinds)):
            dropped.add(index)
        elif line in definitions and (frames_only or found) and definitions[line] not in kept_kinds:
            dropped.add(index)
    return "\n".join(line for index, line in enumerate(lines) if index not in dropped)


def _first(beats: Sequence[Mapping[str, str]], key: str) -> str:
    return next((str(beat.get(key) or "") for beat in beats if str(beat.get(key) or "").strip()), "")


def merge(
    beats: Sequence[Mapping[str, str]], *, model: str, cast: Sequence[str] = (), scenes: Sequence[str] = (),
    props: Sequence[str] = (), costumes: Sequence[tuple[str, str]] = (), fight: bool = False, motions: Sequence[str] = (),
) -> dict[str, str]:
    """几个连续瞬间合成一段时的固定句：每句只写一次，按整段来定。

    锚型与同一人声明按整段的参考图重写；对白语言把各镜开口的人并起来；表演锁按整段的长度写足两句；
    回合锁看整段是不是打戏、有几句台词；结尾三段里只要有一镜是真人演员，整段就按真人演员写。
    """
    if not any(str(beat.get(key) or "").strip() for beat in beats for key in SECTIONS):
        return {}  # 手工拼的或旧的分节：没有骨架句，不凭空补
    family_ = family(model)
    data = _data("anchor_types")
    costume_kind = data["kinds"]["costume"]
    row = _row_pattern()
    # 哪些服装有自己的参考图，各镜的锚型行里写着。
    costume_images = [
        MENTION.sub(lambda match: match.group(1), matched.group("ref"))
        for beat in beats for line in str(beat.get("anchor_types") or "").split("\n")
        if (matched := row.match(line)) and matched.group("type") == costume_kind
    ]
    references = bool(_unique([*cast, *scenes, *props]))
    on_screen: list[str] = []
    off_screen: list[str] = []
    languages = 0
    for beat in beats:
        matched = _LANGUAGE_LINE.match(str(beat.get("dialogue_language") or "").strip())
        if not matched:
            continue
        languages += 1
        for speaker in matched.group("speakers").split("、"):
            name = MENTION.fullmatch(speaker.strip())
            (on_screen if name else off_screen).append(name.group(1) if name else speaker.strip())
    unnamed = str(_data("dialogue_language")["unnamed"])
    off_screen = [name for name in off_screen if name != unnamed]
    locks = [str(beat.get("performance_lock") or "") for beat in beats if str(beat.get("performance_lock") or "").strip()]
    no_sigh = str(_data("performance_lock")["no_sigh"])
    # 背对镜头的瞬间写的是背面的表演锁；整段都是背面才只写它，有一镜看得见脸就写完整的表演锁。
    back_head = str(_data("performance_lock")["back"][0])
    fronts = [lock for lock in locks if not lock.startswith(back_head)]
    # 多个瞬间的一段不算短片段：表演锁两句都写。只有一个瞬间时用它自己的。
    performance = ""
    if locks:
        performance = locks[0] if len(beats) == 1 else performance_lock(
            family_, script="" if all(no_sigh in lock for lock in locks) else "叹气", back=not fronts,
        )
    chain = _data("chain_lock")
    dialogue_policy = str(_data("text_policy")["dialogue"])
    talking = [str(beat.get("text_policy") or "").strip() == dialogue_policy for beat in beats]
    # 有台词的镜头各算一个话轮；哪一镜自己就有两句以上台词(它的回合锁写着)，再多算一个。
    turns = sum(talking) + sum(str(beat.get("chain_lock") or "").strip() == chain["talk"] for beat in beats)
    fight = fight or any(str(chain["fight"]) in str(beat.get("chain_lock") or "") for beat in beats)
    portraits = [bool(str(beat.get("portrait_safety") or "").strip()) for beat in beats if str(beat.get("performance_lock") or "").strip()]
    real_person = bool(portraits) and not all(portraits)
    review_safe = any(str(_data("portrait_safety")["review_safe"]) in str(beat.get("portrait_safety") or "") for beat in beats)
    return {
        **{key: _first(beats, key) for key in ("pa1", "pa2", "pa3", "sequence_head", "space_axis", "impact_sound", "voice_ban")},
        "anchor_types": anchor_types(cast, scenes, props, costumes, costume_images),
        "same_instance": same_instance(cast, costumes, costume_images, references=references),
        "dialogue_language": dialogue_language(family_, on_screen, off_screen) if languages else "",
        "lens": lens(fight=fight, camera_movement="" if not motions or not all(fixed_camera(motion) for motion in motions) else motions[0]),
        "performance_lock": performance,
        "chain_lock": chain_lock(
            fight=fight, camera_fixed=bool(motions) and all(fixed_camera(motion) for motion in motions), turns=turns,
        ) if len(beats) > 1 else _first(beats, "chain_lock"),
        **tail(people=bool(locks), real_person=real_person, review_safe=review_safe, dialogue=any(talking)),
    }


__all__ = [
    "HEADERS", "NOT_FOR_REWRITE", "SECTIONS", "SHORT_SECONDS", "anchor_types", "chain_lock", "close_size", "dialogue_language", "family",
    "first_sound_marked", "fixed_camera", "headers", "impact_sound", "lens", "listener_camera", "listener_camera_line", "merge",
    "performance_lock", "same_instance", "settle", "sfx_marks", "space_axis",
    "tail", "voice_ban",
]
