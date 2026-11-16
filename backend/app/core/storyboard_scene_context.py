"""Scene-scoped production references; no provider calls or persistence."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from app.core import breakdown_kinds, character_variants, emotion_points, literary, prompt_data, prop_scale, real_person, scene_cast
from app.core.face_card import parse_face_card, render_face_card
from app.core import wuxia_vfx
from app.core.scene_turnaround import SCENE_REVERSE_SLOT, SCENE_VIEW_LABELS, SCENE_VIEW_PURPOSES

# 提示词里的句子、参考图那句锁定说明、报错、认人的词表和正则：app/data/prompt/storyboard_scene_context.json。
_WORDING = "storyboard_scene_context"


def _says(key: str, /, **values: object) -> str:
    """场内资料措辞表里的一句，填好值(``key`` 只按位置传：模板里可以有叫 ``key`` 的值)。"""
    return str(prompt_data.load(_WORDING)["says"][key]).format(**values)


def _word(key: str) -> str:
    """措辞表里原样使用的一个词(分隔符、标记、正则模板)。"""
    return prompt_data.text(_WORDING, key)


def _pattern(key: str) -> re.Pattern[str]:
    """措辞表里的一条正则；写成数组的按顺序直接相连。"""
    body = prompt_data.value(_WORDING, key)
    return re.compile("".join(body) if isinstance(body, list) else str(body))


#: 人会拿、会碰、会坐进去的物件：视频提示词里和道具一样写成「名字（参考图N）」的道具锚，持有、接触、递接都按它认。
OBJECT_KINDS = ("prop", "product", "vehicle")
KINDS = {"scene": "scenes", "prop": "props", "costume": "costumes", "effect": "effects", "product": "products", **breakdown_kinds.CATALOG_KEYS}
LABELS = {
    **{str(kind): str(label) for kind, label in prompt_data.value(_WORDING, "labels").items()},
    **breakdown_kinds.LABELS,
}
#: 妆效不在这里：只有一处伤的人，不等于每场都带着它，受伤之前的戏不能画上。
EMPTY_ACTOR = _word("empty_actor")
_EMPTY_NAMES = {*prompt_data.words(_WORDING, "empty_names"), EMPTY_ACTOR}
# 剧本里没有名字的人(「一双粗手」「门外的人影」)：分镜表照实写成「未露面按压者」「画外声音」这类称呼，
# 它们不是编出来的新角色，也没有设定集可绑——不算未出场角色，也不进身份参考。
_ANONYMOUS = _pattern("anonymous_pattern")
# 只有身份、没有名字的跑龙套(「管事」「仆妇甲」「侍卫二」)：剧本按职务称呼他们，同样不是新角色。
# 带姓的「李管事」是有名有姓的人，不在此列，照常按角色核对。
_EXTRA_ROLE = _pattern("extra_role_pattern")


# 剧本里成片的人(「玄黑人影挤满石阶」「黑衣人」「阶下众人」)：分镜照剧本写进入镜列，是布景不是角色。
# 「演武场弟子」「外门弟子们」是一群没有名字的人；剧本里有名有姓的弟子在角色表里，不走这里。
_CROWD = _pattern("crowd_pattern")
_BRACKETS = _pattern("bracket_pattern")
_HEAD_SPLIT = _pattern("profile_head_split")
_TITLE_SPLIT = _pattern("title_split")
_NAMES_SPLIT = _pattern("names_split")
_STEM_SPLIT = _pattern("stem_split")
_STEM_SUFFIX = _pattern("stem_suffix_pattern")
_STEM_COUNT = _pattern("stem_count_pattern")
_LABEL_SEPARATOR = _word("label_separator")
# 参考图那句里不出现「；」「。」：换成逗号，两端去掉。
_SENTENCE_MARKS = _pattern("sentence_marks_pattern")
_CLAUSE = _word("clause_separator")
_TRIM = _word("trim_chars")
_MAKEUP_MARKER = _word("makeup_marker")
_OUTFIT_MARKER = _word("outfit_marker")
_PLACEHOLDER = _pattern("placeholder_pattern")
_NO_DIALOGUE = {"", *prompt_data.words(_WORDING, "no_dialogue")}


def _is_anonymous(name: str) -> bool:
    return bool(_ANONYMOUS.match(name) or _EXTRA_ROLE.match(name) or _CROWD.search(name))


def is_uncast(name: str) -> bool:
    """空镜标记、无名路人和按职务称呼的跑龙套：不是角色，没有设定集要绑。"""
    name = _text(name)
    return not name or name in _EMPTY_NAMES or _is_anonymous(name)


# 「女配角」「反派」是戏份，不是称呼，好几个人共用，不能拿来认人。
_BILLING = _pattern("billing_pattern")


def cast_aliases(task: dict) -> dict[str, str]:
    """剧本里的称呼 → 设定集里的演员名。

    剧本和分镜表常只叫「侯府嫡女」，第 3 阶段给这个人起了名字(陆婉)，并把称呼写在设定开头
    「侯府嫡女／女配角；圆鹅蛋脸……」。没有这层对照，分镜和视频会去找一个叫「侯府嫡女」的演员——
    要么找不到身份视图被拦下，要么绑到素材库里一张过期的旧脸。称呼只认唯一对应的那一个人；
    称呼本身就是某个演员的名字时不改。
    """
    assets = task.get("assets") if isinstance(task.get("assets"), dict) else {}
    people = [item for item in assets.get("3_characters") or [] if isinstance(item, dict) and _text(item.get("name"))]
    names = {_text(item["name"]) for item in people} | {_text(name) for name in (assets.get("3_sheets") or {})}
    found: dict[str, set[str]] = {}

    def claim(title: str, name: str) -> None:
        title = _BRACKETS.sub("", _text(title)).strip()
        if 2 <= len(title) <= 12 and title != name and not _BILLING.match(title) and not is_uncast(title):
            found.setdefault(title, set()).add(name)

    for item in people:
        name = _text(item["name"])
        head = _HEAD_SPLIT.split(_text(item.get("desc")), maxsplit=1)[0]
        if len(head) <= 40:
            for title in _TITLE_SPLIT.split(head):
                claim(title, name)
        for alias in _names(item.get("aliases")):
            claim(alias, name)
    state = assets.get("2_screenwriting") if isinstance(assets.get("2_screenwriting"), dict) else {}
    inventory = (state.get("inventory") or {}).get("characters") if isinstance(state.get("inventory"), dict) else {}
    for name, entry in (inventory or {}).items() if isinstance(inventory, dict) else ():
        if _text(name) in names and isinstance(entry, dict):
            for alias in _names(entry.get("aliases")):
                claim(alias, _text(name))
    return {title: next(iter(owners)) for title, owners in found.items() if len(owners) == 1 and title not in names}


def name_titles(text: str, aliases: dict[str, str]) -> str:
    """视频提示词里写的称呼(「侯府嫡女」)换成那位演员的 @[名字]，让它指向她的参考图；服装名里括注的称呼不动。"""
    for title, owner in sorted(aliases.items(), key=lambda item: len(item[0]), reverse=True):
        text = re.sub(_word("title_mention_pattern").format(title=re.escape(title)), f"@[{owner}]", text)
    return text


def _named(name: str, text: str, aliases: dict[str, str]) -> bool:
    """正文点到这个人：叫名字，或叫他的称呼。"""
    return name in text or any(owner == name and title in text for title, owner in aliases.items())


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _names(value: Any) -> list[str]:
    if isinstance(value, str):
        value = _NAMES_SPLIT.split(value)
    return (
        list(dict.fromkeys(_text(name) for name in (value or []) if _text(name)))
        if isinstance(value, list)
        else []
    )


def _scoped(item: dict, scene_id: str) -> bool:
    metadata = item.get("metadata") or {}
    scope = (
        item.get("scene_ids")
        or item.get("scene_id")
        or metadata.get("scene_ids")
        or metadata.get("scene_id")
    )
    return not scope or scene_id in _names(scope)


#: 按名字里的片段也认得到的类型：拆解目录里的名字常带修饰、方位或并列(「凹坑磨石」「墙角接雨木盆」「长木案与矮条凳」
#: 「油灯爆灯花」)，剧本和分镜只写「磨石」「接雨木盆」「长木案」「灯花」。特技是一段动作的名字，不按片段认。
_NOUN_KINDS = (*OBJECT_KINDS, "set_dressing", "effect")
_BRACKETED_NOTE = _pattern("bracketed_note_pattern")
_NAME_PARTS = _pattern("name_part_split")
_PIECE_LEAD = _pattern("name_piece_lead")
# 光、烟、影这类泛泛的画面词不能单独当认资产的片段：「窗外微光」不是「剑自出鞘三寸微光」。
_PIECE_STOP = frozenset(prompt_data.value(_WORDING, "name_piece_stop"))


def head_noun(item: Mapping[str, Any]) -> str:
    """物件名字结尾的那个物件名词，按道具尺寸表认(两个字以上)：「凹坑磨石」→ 磨石，「马蹄金与钱袋」→ 钱袋。

    名字本身就是表里那个词、或认不出时是空串(那时整名匹配已经够用)。
    """
    bare = _BRACKETED_NOTE.sub("", _text(item.get("name"))).strip()
    scale = prop_scale.lookup(bare)
    if scale is None or len(scale.name) < 2 or scale.name == bare or not bare.endswith(scale.name):
        return ""
    return scale.name


def name_pieces(item: Mapping[str, Any]) -> frozenset[str]:
    """认这件资产的片段：并列的每一样(按「与」「和」「、」分开)，和每一样两个字以上的结尾，加上尺寸表认出的物件名词。

    「墙角接雨木盆」→ 接雨木盆、木盆……；「长木案与矮条凳」→ 长木案、木案、矮条凳、条凳……。以「的」「之」开头的结尾不算
    (「未开刃的刀」不靠「的刀」认)，name_piece_stop 里的泛泛画面词(微光、烟雾)也不算。只对道具、商品、车辆、置景和特效。
    """
    if str(item.get("kind") or "") not in _NOUN_KINDS:
        return frozenset()
    bare = _BRACKETED_NOTE.sub("", _text(item.get("name"))).strip()
    pieces = {head_noun(item)}
    for part in _NAME_PARTS.split(bare):
        part = part.strip()
        pieces.update(part[start:] for start in range(len(part) - 1) if not _PIECE_LEAD.match(part[start:]))
    pieces.discard("")
    pieces.discard(bare)
    return frozenset(pieces - _PIECE_STOP)


def named_by_noun(item: Mapping[str, Any], text: str, peers: Iterable[Mapping[str, Any]]) -> bool:
    """名字没原样出现、但写了它的一个片段(见 :func:`name_pieces`)，而且同类里只有它有这个片段：分镜写「接雨木盆」就是
    「墙角接雨木盆」，剧本写「磨石」就是「凹坑磨石」。两件都有这个片段的(「七缺口钝刀」「旧钝刀」都有「钝刀」)谁也不认，免得绑错。
    """
    pieces = name_pieces(item)
    if not pieces:
        return False
    text = str(text or "")
    others = [name_pieces(other) for other in peers if other is not item and _text(other.get("name")) != _text(item.get("name"))]
    return any(piece in text and not any(piece in other for other in others) for piece in pieces)


def mentioned(item: dict, text: str) -> bool:
    name = _text(item.get("name"))
    # 素材库条目的别名记在元数据里(并掉的重复条目的旧名字也在这)：剧本写旧名字照样认到它。
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    aliases = _names(item.get("aliases")) + _names(metadata.get("aliases")) + _names(name)
    # Catalog labels commonly append staging annotations to the actual name.
    stem = _STEM_SPLIT.split(name)[0]
    stem = _STEM_SUFFIX.sub("", stem)
    # A label such as 血痕三道 names the same effect as 三道血痕.
    stem = _STEM_COUNT.sub("", stem)
    # 「沈砚·额角刀伤」: the script says 额角刀伤, not the whole label.
    tail = stem.rsplit(_LABEL_SEPARATOR, 1)[-1]
    return any(len(alias) >= 2 and alias in text for alias in [name, stem, tail, *aliases])


def _line(item: dict) -> str:
    return _says("line", name=item["name"], description=item.get("description") or _says("line_fallback"))


def costume_owner(item: dict, name: str) -> bool:
    # '贺兰霆亲卫' and '贺兰霆手下' describe other actors, not his outfit.
    return name in item["name"] or bool(
        re.match(
            _word("costume_owner_pattern").format(name=re.escape(name)), _text(item.get("description"))
        )
    )


def costume_wearers(references: list[dict], characters: Sequence[str], aliases: Mapping[str, str] | None = None) -> list[tuple[str, str]]:
    """本镜各人穿什么：(穿着者, 造型名)。表演妆造直接写造型名；旧项目的服装图，名字或描述里叫的是称呼(侯府嫡女)时也认得出是谁。"""
    aliases = dict(aliases or {})
    cast = [str(name).strip() for name in characters if str(name).strip()]
    labels = [(name, name) for name in cast] + [(title, owner) for title, owner in aliases.items() if owner in cast]
    out: list[tuple[str, str]] = []
    for item in references:
        if item.get("kind") == "actor" and item.get("variant") and _text(item.get("name")) in cast:
            # 还没画的造型：参考图上不是这身，不绑「以参考图为准」，衣服由参考图那句的文字说。
            if item.get("look_undrawn"):
                continue
            if (item["name"], str(item["variant"])) not in out:
                out.append((item["name"], str(item["variant"])))
            continue
        if item.get("kind") != "costume" or not _text(item.get("name")):
            continue
        wearer = next((owner for label, owner in labels if costume_owner(item, label)), "")
        if wearer and (wearer, item["name"]) not in out:
            out.append((wearer, item["name"]))
    return out


def compile_scene_context(
    task: dict, scene: dict, elements: list[dict] | None = None
) -> dict:
    """Bind only source-backed assets, never use the first two global actors."""
    assets = task.get("assets") or {}
    scene_id = _text(scene.get("scene_id")) or "E1S01"
    content = _text(scene.get("content"))
    dialogue = _text(scene.get("dialogue"))
    script = content + (
        _says("script_dialogue", dialogue=dialogue) if dialogue and dialogue not in _NO_DIALOGUE else ""
    )
    # 编剧定的情绪点(钩子/冲突/反转…)：分镜师照它定这一场打到哪一下。
    emotion_note = emotion_points.scene_note(scene.get("emotion_point"))
    if emotion_note:
        script += f"\n{emotion_note}"
    # 题眼台词落在这一格：画面给这句留停留。
    key_note = literary.scene_note(scene.get("key_line"))
    if key_note:
        script += f"\n{key_note}"
    profiles = {
        item["name"]: _text(item.get("desc"))
        for item in assets.get("3_characters", [])
        if isinstance(item, dict) and _text(item.get("name"))
    }
    aliases = cast_aliases(task)
    actor_elements: dict[str, dict[str, Any]] = {}
    # A derived look (少年 / 婚纱 / 受伤后) is an actor element that names its character;
    # it dresses that character where the story calls for it and is never a character itself.
    base_actors, variants = character_variants.split(
        item for item in elements or [] if item.get("kind") == "actor" and _scoped(item, scene_id)
    )
    for item in base_actors:
        # 素材库里以称呼命名的旧条目(「侯府嫡女」)就是有名字的那个演员，由设定集那位出场。
        if item["name"] not in aliases:
            actor_elements.setdefault(item["name"], item)
    all_names = list(dict.fromkeys([*profiles, *actor_elements]))
    characters = _names(scene.get("characters")) or [
        name for name in all_names if _named(name, script, aliases)
    ]
    if not _names(scene.get("characters")):
        # 出场名单是空的：剧本只描述外貌没写名字的人(「药白素衣的年轻女子…腕上药渍」)，按他的定妆图(表演妆造)认出来补进来，
        # 他的定妆照、妆造才进得了提示词。名单写明了人的，那是编剧定的，不补。
        characters = [*characters, *scene_cast.described(script, variants, characters)]
    characters = list(dict.fromkeys(aliases.get(name, name) for name in characters if name not in _EMPTY_NAMES))
    sheets = assets.get("3_sheets") or {}
    actors: list[dict[str, Any]] = []
    for name in characters:
        library_actor = actor_elements.get(name, {})
        description = _text(library_actor.get("description")) or profiles.get(name, "")
        profiles[name] = description
        actor = {
            **library_actor,
            "kind": "actor",
            "name": name,
            "description": description,
            "image_url": library_actor.get("image_url") or sheets.get(name) or "",
        }
        own_variants = variants.get(name) or []
        if own_variants:
            actor["variants"] = own_variants
            actor["base_description"], actor["base_image_url"] = actor["description"], actor["image_url"]
            actor["base_face_url"] = actor.get("face_url") or ""
        chosen = character_variants.pick(
            own_variants, text=script, episode=character_variants.episode_of(scene_id), scene=character_variants.scene_of(scene_id),
        )
        actor = character_variants.apply(actor, chosen)
        profiles[name] = actor["description"]
        actors.append(actor)

    catalog = (assets.get("2_breakdown") or {}).get("production_assets") or {}
    # 物件、置景和特效也按这一场已经写好的分镜认：剧本只写「屋角木盆」，分镜写到「接雨木盆」「墙上铁钩」也算这一场有。
    shot_text = "\n".join(
        _text(shot.get("desc")) for shot in (assets.get("4") or [])
        if isinstance(shot, dict) and _text(shot.get("scene_id")) == scene_id
    )
    object_text = f"{script}\n{shot_text}" if shot_text else script
    # 戏服和妆效已经画在定妆图上：这些条目和旧项目的服装图、妆效图不再绑，免得一个人穿两身。
    already_worn = {
        name for looks in variants.values() for item in looks
        if character_variants.is_look(item) and item.get("image_url")
        for name in character_variants.worn_names(item)
    }
    context: dict[str, Any] = {
        "scene_id": scene_id,
        "script": script,
        "characters": characters,
        "profiles": {name: profiles.get(name, "") for name in characters},
        "all_character_names": all_names,
        "actors": actors,
        "cast_aliases": aliases,
    }
    for kind, key in KINDS.items():
        candidates = {}
        for value in catalog.get(key) or []:
            item = value if isinstance(value, dict) else {"name": value}
            if _text(item.get("name")) and _scoped(item, scene_id):
                candidates[item["name"]] = {**item, "kind": kind}
        library_names = set()
        for item in elements or []:
            if item.get("kind") == kind and _scoped(item, scene_id):
                if item["name"] not in library_names:
                    candidates[item["name"]] = item
                    library_names.add(item["name"])
                    # 拆解目录里还写着并掉的旧名字(「裴照腰佩长剑」)：那条由库里留下的这条代表，不再单列一条没图的。
                    for alias in _names((item.get("metadata") or {}).get("aliases") if isinstance(item.get("metadata"), dict) else None):
                        if alias != item["name"] and alias in candidates and not candidates[alias].get("id"):
                            del candidates[alias]
        selected = []
        for item in candidates.values():
            if kind in ("costume", "makeup") and item["name"] in already_worn:
                continue
            explicit_scope = (
                item.get("scene_ids")
                or item.get("scene_id")
                or (item.get("metadata") or {}).get("scene_ids")
                or (item.get("metadata") or {}).get("scene_id")
            )
            text = object_text if kind in _NOUN_KINDS else script
            matched = bool(explicit_scope) or mentioned(item, text) or named_by_noun(item, text, candidates.values())
            if kind == "costume" and not matched:
                # 服装名可能写名字也可能写称呼(「陆婉（侯府嫡女）·石榴红襦裙」)：两种叫法都算这个人。
                labels = [*characters, *(title for title, owner in aliases.items() if owner in characters)]
                owners = [label for label in labels if costume_owner(item, label)]
                # A single character's alternate outfits must not all appear in
                # one shot. Without a scene/explicit name, use only a unique look.
                matched = any(
                    sum(costume_owner(other, name) for other in candidates.values())
                    == 1
                    for name in owners
                )
            if matched:
                selected.append(item)
        context[key] = selected
    lines = [
        _says("prompt_scene", scene_id=scene_id, script=script),
        _says("prompt_scope"),
    ]
    for kind, items in [
        ("actor", actors),
        *((kind, context[key]) for kind, key in KINDS.items()),
    ]:
        lines.append(
            _says(
                "prompt_section", label=LABELS[kind],
                body="\n".join(_line(item) for item in items) or _says("prompt_section_empty"),
            )
        )
    context["prompt"] = "\n".join(lines)
    return context


def look_makeup(description: str) -> str:
    """一身妆造(或穿着它的角色设定)里的妆效文字；没写妆效时是空串。"""
    _before, marker, after = str(description or "").partition(_MAKEUP_MARKER)
    return after.strip(_TRIM) if marker else ""


def look_outfit(description: str) -> str:
    """穿着妆造的角色设定里那身衣服的文字(「服装：」到「妆效：」之间)；没写时是空串。"""
    _before, marker, after = str(description or "").partition(_OUTFIT_MARKER)
    return after.split(_MAKEUP_MARKER)[0].strip(_TRIM) if marker else ""


def look_makeup_note(makeup: str, *, panel: bool = False) -> str:
    """跟在参考图那句后面的妆效：定妆图把左右画反了，也按文字画。句中不用「；」「。」。措辞在 character_looks.json。"""
    text = _SENTENCE_MARKS.sub(_CLAUSE, str(makeup or "")).strip(_CLAUSE)
    return prompt_data.text("character_looks", "panel_look_makeup" if panel else "shot_look_makeup").format(text) if text else ""


def look_outfit_note(name: str, variant: str, outfit: str, *, drawn: bool = True) -> str:
    """跟在参考图那句后面：这个人这一镜按剧情穿的那身是什么。还没画成定妆图时写明衣服只按文字。

    句中不用「；」「。」，参考图被路由去掉时这句留下，衣服的文字照样在提示词里。措辞在 character_looks.json。
    """
    text = _SENTENCE_MARKS.sub(_CLAUSE, str(outfit or "")).strip(_CLAUSE)[: prompt_data.number("character_looks", "outfit_limit")]
    if not (variant and text):
        return ""
    return prompt_data.text("character_looks", "shot_look_outfit").format(name, variant, text) + (
        "" if drawn else prompt_data.text("character_looks", "shot_look_by_text")
    )


def dress_cast_looks(looks: Mapping[str, str], references: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """视频提示词「人物外貌」用的人物卡：本镜按剧情换了妆造的人，设定集上那身衣服换成这身。"""
    worn = {
        str(item.get("name")): str(item.get("outfit"))
        for item in references if item.get("kind") == "actor" and item.get("variant") and item.get("outfit")
    }
    dressed = dict(looks)
    for name, outfit in worn.items():
        if name not in dressed:
            continue
        card = parse_face_card(str(dressed[name] or ""))
        face = render_face_card(card, include_other=False) if card.has_face_layers else str(dressed[name] or "").strip(_TRIM)
        dressed[name] = _word("look_separator").join(part for part in (face, f"{_OUTFIT_MARKER}{outfit}") if part)
    return dressed


def real_size_note(kind: str, name: str, description: str = "", metadata: Mapping[str, Any] | None = None) -> str:
    """道具、商品和车辆的真实大小，跟在参考图那句后面。句中不用「；」「。」。

    参照表里有长宽高就写长宽高；没有时写第 3 阶段画这件物件的设定图时用的最长边(人填的、描述里写明的或按类别估的，
    见 prop_turnaround.plan_prop)——设定图就是按这个长度画的，镜头里跟人同框也按它。只有名字、连描述都没有的写不出大小，是空串。
    """
    if kind not in OBJECT_KINDS:
        return ""
    scale = prop_scale.lookup(name)
    if scale is not None:
        return prompt_data.text("prop_scale", "reference_size").format(scale.size_text())
    if not str(description or "").strip() and not (metadata or {}).get("prop_length_cm"):
        return ""
    from app.core.prop_turnaround import plan_prop

    manual = (metadata or {}).get("prop_length_cm")
    plan = plan_prop(name, str(description or ""), length_cm=float(manual) if isinstance(manual, (int, float)) and manual > 0 else None)
    return prompt_data.text("prop_scale", "reference_length").format(f"{plan.longest_cm:g}")


def drawn_set(item: Mapping[str, Any]) -> list[str]:
    """这件资产的图和哪几样配套画在一起(出图时记在元数据 drawn_together / drawn_with 里)：[长的那样, 其余几样…]；没有就是空表。"""
    metadata = item.get("metadata") if isinstance(item.get("metadata"), Mapping) else {}
    name = _text(item.get("name"))
    together = [_text(other) for other in metadata.get("drawn_together") or [] if _text(other)] if isinstance(metadata.get("drawn_together"), list) else []
    if together:
        return list(dict.fromkeys([name, *together]))
    partner = _text(metadata.get("drawn_with"))
    return list(dict.fromkeys([partner, name])) if partner and partner != name else []


def _set_note(number: int, reference: Mapping[str, Any], size: str) -> str:
    """配套图那一句：图里画了哪几样；本镜只用到其中几样时说明其余的不进画面。只用一样时带上它的真实大小。"""
    def names(items: Sequence[str]) -> str:
        return _says("set_joiner").join(_says("set_name", name=name) for name in items)

    members = [str(name) for name in reference.get("set") or []]
    used = [str(name) for name in reference.get("used") or []]
    note = _says("set_reference", number=number, names=names(members))
    if used and set(used) != set(members):
        note += _says("set_only", used=names(used))
    return note + (size if len(used) == 1 else "")


def reference_note(number: int, reference: dict, *, label: str = "") -> str:
    """参考图N 只锁一件资产的那句话。

    场地图写明它锁的是空间：布局事实(门在画面左侧、窗在画面右侧)，图中人物不作参考；场地设定图
    只有一种天色，光线与时段以本场为准——雨夜戏照着白天的场地图画，会画成阴天白天；
    场地的额外视角(45°、纵深、细节)写明各自用来做什么。句中不出现「；」「。」，
    这样 ``video_references.renumber_reference_mentions`` 能整句改号或整句删掉。
    """
    kind, name = str(reference.get("kind") or ""), str(reference.get("name") or "")
    label = label or LABELS.get(kind, kind)
    size = str(reference.get("size") if "size" in reference else real_size_note(kind, name))
    if reference.get("set"):
        return _set_note(number, reference, size)
    if kind in breakdown_kinds.KINDS:
        return breakdown_kinds.reference_note(number, kind, name) + size
    if kind == "actor" and reference.get("real_person") and reference.get("view") == "face":
        outfit = _SENTENCE_MARKS.sub(_CLAUSE, str(reference.get("outfit") or "")).strip(_CLAUSE)
        variant = _SENTENCE_MARKS.sub(_CLAUSE, str(reference.get("variant") or "")).strip(_CLAUSE)
        return (
            real_person.say("reference_face", number, name)
            + (real_person.say("outfit_by_text", variant or _says("real_person_variant_fallback"), outfit) if outfit else "")
            + look_makeup_note(str(reference.get("look_makeup") or ""))
        )
    if kind == "actor" and reference.get("view") == "face":
        return prompt_data.text("character_looks", "shot_headshot").format(number, label, name)
    if kind == "actor":
        variant = _SENTENCE_MARKS.sub(_CLAUSE, str(reference.get("variant") or "")).strip(_CLAUSE)
        makeup = _SENTENCE_MARKS.sub(_CLAUSE, str(reference.get("makeup") or "")).strip(_CLAUSE)
        outfit = look_outfit_note(name, variant, str(reference.get("outfit") or ""), drawn=not reference.get("look_undrawn"))
        if variant and reference.get("look_undrawn"):
            lead = prompt_data.text("character_looks", "shot_look_undrawn").format(number, label, name)
        else:
            lead = _says(
                "actor_reference", number=number, label=label, name=name,
                variant=_says("actor_variant", variant=variant) if variant else "",
            )
        return (
            lead + outfit
            + look_makeup_note(str(reference.get("look_makeup") or ""))
            + (real_person.say("reference_body") if reference.get("real_person") else "")
            + (_says("actor_makeup_by_text", makeup=makeup) if makeup else "")
        )
    if kind != "scene":
        # 特效图只是一瞬：写明它在镜头里什么时候出现、怎么照人(措辞在 wuxia_vfx.json)。
        timing = prompt_data.text("wuxia_vfx", "shot_effect_reference") if kind == "effect" else ""
        return _says("object_reference", number=number, label=label, name=name) + timing + size
    view = str(reference.get("view") or "") or "scene_main"
    layout = _SENTENCE_MARKS.sub(_CLAUSE, _text(reference.get("layout"))).strip(_CLAUSE)
    frame = str(reference.get("frame") or "")
    if reference.get("desk"):
        # 本镜带着导演台白模(静帧或白模视频)：站位与家具位置归白模，场地图只取质感(措辞在 scene_views.json)。
        direction = prompt_data.value("scene_views", "direction_labels").get(view)
        named = direction or (SCENE_VIEW_LABELS.get(view, "") if view != "scene_main" else "")
        return (
            _says("scene_reference", number=number, label=label, name=name,
                  scope=prompt_data.text("scene_views", "desk_scope").format(named))
            + (_says("scene_layout", layout=layout) if layout else "")
            + (prompt_data.text("scene_views", "desk_composition" if frame == "composition" else frame) if frame else "")
            + (prompt_data.text("scene_views", "pair_note") if reference.get("pair") else "")
            + _says("scene_reference_tail")
        )
    # 只核对陈设的视角图不再写它平时用来做什么(「用于走位透视」)，免得和「不决定本镜构图」打架。
    purpose = "" if frame in ("space_only", "reverse", "reverse_space") else _says("scene_purpose", purpose=SCENE_VIEW_PURPOSES.get(view, ""))
    # 主场景全景与反打视角写明哪张是正面、哪张是反打(词表在 scene_views.json)；其他视角照旧。
    direction = prompt_data.value("scene_views", "direction_labels").get(view)
    if direction:
        scope = prompt_data.text("scene_views", "direction_scope").format(direction)
    elif view in SCENE_VIEW_PURPOSES and view != "scene_main":
        scope = _says("scene_view_scope", view=SCENE_VIEW_LABELS[view], purpose=purpose)
    else:
        scope = _says("scene_default_scope")
    return (
        _says("scene_reference", number=number, label=label, name=name, scope=scope)
        + (_says("scene_layout", layout=layout) if layout else "")
        + (prompt_data.text("scene_views", frame) if frame else "")
        # 正面与反打一起发出时说一次：两张是同一场地、同一画风。写在本句里，反打那张没发出去就一起删掉。
        + (prompt_data.text("scene_views", "pair_note") if reference.get("pair") else "")
        + _says("scene_reference_tail")
    )




def _framing(shot: Mapping[str, Any]) -> str:
    return " ".join(_text(shot.get(key)) for key in ("size", "angle", "motion", "framing"))


def in_exchange(shot: Mapping[str, Any], on_screen: int) -> bool:
    """这一镜是不是一组正反打里的一镜：取景写了反打 / 过肩 / 正反打，或有台词且画面里有两人以上。词表在 scene_views.json。"""
    framing = _framing(shot).lower()
    words = (*prompt_data.words("scene_views", "reverse_words"), *prompt_data.words("scene_views", "exchange_words"))
    if any(word.lower() in framing for word in words):
        return True
    return _text(shot.get("dialogue")) not in _NO_DIALOGUE and on_screen >= 2


def scene_frame_view(shot: Mapping[str, Any], available: set[str], *, empty_shot: bool) -> str | None:
    """这一镜用场地的哪张视角图定构图；反打镜头没有反打视角时返回 None(没有一张对得上方向)。

    按景别、角度、运镜的关键词挑，挑中的视角没有就退回主场景全景；细节图只给无人的插入镜头。
    关键词在 scene_views.json。
    """
    framing = _framing(shot)
    # 「正反打」里含着「反打」：它只说这一镜在一组正反打里，不说这一镜是反打那一侧。
    sided = framing
    for word in prompt_data.words("scene_views", "exchange_words"):
        sided = sided.replace(word, " ")
    if any(word in sided for word in prompt_data.words("scene_views", "reverse_words")):
        return SCENE_REVERSE_SLOT if SCENE_REVERSE_SLOT in available else None
    fallback = "scene_main" if "scene_main" in available else next(iter(sorted(available)), None)
    return next(
        (
            view for view, words in prompt_data.value("scene_views", "pick")
            if view in available and (view != "scene_detail" or empty_shot) and any(word in framing for word in words)
        ),
        fallback,
    )


def bind_scene_frames(references: list[dict], shot: Mapping[str, Any], *, empty_shot: bool, desk: bool = False) -> None:
    """同一场地发了几张视角图时，给每张写明这一镜里的职责(``frame``)。

    几张图不分职责一起发，模型会把另一个方向的前景(反向那张图里的台阶、门)混进本镜。一张是本镜唯一的
    场景构图来源，其余只核对陈设；反打镜头没有反打视角时，全部只核对陈设、写明方向相反。正面(主场景全景)
    与反打视角成对发出时，朝本镜方向的那张定构图，另一张只核对机位身后那一侧；反打那张不定构图时用它自己的
    职责(``reverse_space``)，并标上 ``pair``，那句话里说一次两张是同一场地、同一画风。

    ``desk``：本镜带着导演台白模(有效的静帧或白模视频)，每张场地图都标上 ``desk``，只取材质、色调、光影与年代感，
    站位与家具位置以白模为准(见 :func:`reference_note`)；正反打的职责照旧写，但没有一张是构图来源。
    """
    scenes = [item for item in references if item.get("kind") == "scene"]
    for item in scenes:
        if desk:
            item["desk"] = True
        else:
            item.pop("desk", None)
    for name in dict.fromkeys(str(item.get("name") or "") for item in scenes):
        group = [item for item in scenes if item.get("name") == name]
        views = {str(item.get("view") or "scene_main") for item in group}
        chosen = scene_frame_view(shot, views, empty_shot=empty_shot)
        if chosen is None:
            for item in group:
                item["frame"] = "reverse"
        elif len(group) > 1:
            for item in group:
                view = str(item.get("view") or "scene_main")
                if view == chosen:
                    item["frame"] = "composition"
                else:
                    item["frame"] = "reverse_space" if view == SCENE_REVERSE_SLOT else "space_only"
        paired = {"scene_main", SCENE_REVERSE_SLOT} <= views
        for item in group:
            if paired and item.get("view") == SCENE_REVERSE_SLOT:
                item["pair"] = True
            else:
                item.pop("pair", None)


def _crowd_moves(item: dict, text: str, key: str) -> bool:
    """这段文字里，这批群演的名字后面不远处有没有进场 / 离场的词。"""
    name = _text(item.get("name"))
    stem = _STEM_SPLIT.split(name)[0]
    window = prompt_data.number("crowd_presence", "window")
    words = prompt_data.words("crowd_presence", key)
    for alias in dict.fromkeys(alias for alias in (name, stem, *_names(item.get("aliases"))) if len(alias) >= 2):
        for match in re.finditer(re.escape(alias), text):
            if any(word in text[match.end(): match.end() + window] for word in words):
                return True
    return False


def crowd_on_set(context: dict, shots: Sequence[Mapping[str, Any]]) -> list[set[str]]:
    """一场戏里每一镜在场的群演名字，按镜头顺序。

    群演只在点到名字的那一镜绑上，前一镜教室还空着、后一镜突然坐满。这里按剧本把在场的时段连起来：
    本场剧本提到的群演从第一镜起就在场；第一次露面那一镜写的是进场(涌入、走进)，就从那一镜起在场；
    某一镜写了离场(退下、散去)，那一镜之后就不在。词表在 crowd_presence.json。
    """
    actions = [_text(shot.get("desc")) for shot in shots]
    on_set: list[set[str]] = [set() for _ in shots]
    for item in context.get("extras") or []:
        first = next((index for index, action in enumerate(actions) if mentioned(item, action)), None)
        start = first if first is not None and _crowd_moves(item, actions[first], "enter_words") else 0
        for index in range(start, len(shots)):
            on_set[index].add(item["name"])
            if mentioned(item, actions[index]) and _crowd_moves(item, actions[index], "leave_words"):
                break
    return on_set


def crowd_lines(context: dict, shot: Mapping[str, Any], on_set: Iterable[str]) -> list[str]:
    """这一镜没点名、但本场还在场的群演，写成一句话放进视频提示词(没有参考图时只能靠这句)。"""
    names = set(on_set)
    action = _text(shot.get("desc"))
    return [
        prompt_data.text("crowd_presence", "shot_line").format(item["name"], _text(item.get("description")) or _says("crowd_fallback"))
        for item in context.get("extras") or [] if item["name"] in names and not mentioned(item, action)
    ]


_LATER_NOTE = _pattern("later_note_pattern")
_SENTENCES = _pattern("sentence_split_pattern")


def looks_only(description: str) -> str:
    """资产描述里只留它长什么样：说哪一集、终局、之后会怎样的句子(「第2集末尾挂上钝刀」)不写进这一镜，免得提前画出来。"""
    return "".join(sentence for sentence in _SENTENCES.split(_text(description)) if sentence.strip() and not _LATER_NOTE.search(sentence))


def unpictured_lines(binding: Mapping[str, Any]) -> list[str]:
    """本镜绑到、却没有参考图的道具、车辆、商品和置景：照资产描述写一句放进视频提示词，模型只看到名字时画不出它。

    特效和特技在「特效」那一节里写，群演见 :func:`crowd_lines`，人物与场地另有锚点。没写描述的不写(名字已在动作里)。
    """
    shown = {(str(item.get("kind")), str(item.get("name"))) for item in binding.get("references") or []}
    lines = []
    for item in binding.get("assets") or []:
        kind, name = str(item.get("kind") or ""), str(item.get("name") or "")
        text = _SENTENCE_MARKS.sub(_CLAUSE, looks_only(_text(item.get("description")))).strip(_CLAUSE)
        if (kind in OBJECT_KINDS or kind == "set_dressing") and (kind, name) not in shown and text:
            lines.append(_says("unpictured_asset", name=name, text=text))
    return list(dict.fromkeys(lines))


def desk_layers(references: Sequence[Mapping[str, Any]], *, desk: bool) -> list[dict]:
    """几个瞬间合成一段时按这一段实际带不带导演台白模重标场地图(返回副本，各瞬间自己的参考不动)。"""
    marked: list[dict] = []
    for item in references:
        copy = dict(item)
        if copy.get("kind") == "scene":
            if desk:
                copy["desk"] = True
            else:
                copy.pop("desk", None)
        marked.append(copy)
    return marked


def identity_sheets(
    sheets: dict, fallback: list[tuple[str, str]], references: list[dict], shot: dict, aliases: dict[str, str]
) -> list[tuple[str, str]]:
    """视频请求里用哪些设定集链接锁脸。

    素材库为本镜给出了参考(有归属的项目)时，本镜的人以素材库的演员图为准——那是本地私有图，
    不会像设定集的签名链接那样过期；设定集只补本镜入镜、素材库却没有给图的人。空镜和只有路人的镜头
    一个都不绑，不再退回「前两位主角」。没有素材库的旧项目保持原来的 ``fallback``。
    """
    if not references:
        return list(fallback)
    covered = {str(item.get("name") or "") for item in references if item.get("kind") == "actor"}
    cast = dict.fromkeys(aliases.get(name, name) for name in _names(shot.get("characters")) if not is_uncast(name))
    return [(name, str(sheets[name])) for name in cast if name not in covered and sheets.get(name)]


def merge_video_references(
    sheets: list[tuple[str, str]], references: list[dict], *, limit: int = 9
) -> tuple[list[str], str]:
    """Five-view sheets first, then the shot's library references; deduplicated.

    Returns the image list for the video provider plus the role lines the prompt
    needs so each reference locks exactly one asset and nothing else.
    """
    entries = _ordered_references(sheets, references, limit=limit)
    images = [str(item["image_url"]) for item in entries]
    notes = [
        reference_note(number, item, label=_says("sheet_label") if item["kind"] == "actor" else "")
        for number, item in enumerate(entries, start=1)
    ]
    return images, _word("note_separator").join(notes)


def _ordered_references(
    sheets: list[tuple[str, str]], references: list[dict], *, limit: int = 9
) -> list[dict]:
    # A character wearing a derived look is locked by that look's image, not the base five-view sheet.
    dressed = {str(item.get("name") or "") for item in references if item.get("kind") == "actor" and item.get("variant") and item.get("image_url")}
    ordered: list[dict] = [{"kind": "actor", "name": name, "image_url": url} for name, url in sheets if url and name not in dressed]
    ordered += [
        {**item, "kind": str(item.get("kind") or ""), "name": str(item.get("name") or ""), "image_url": str(item.get("image_url") or "")}
        for item in references
        if item.get("image_url")
    ]
    entries: list[dict] = []
    seen: set[str] = set()
    for item in ordered:
        if item["image_url"] in seen or len(entries) >= limit:
            continue
        seen.add(item["image_url"])
        entries.append(item)
    return entries


def video_reference_entries(
    sheets: list[tuple[str, str]], references: list[dict], *, limit: int = 9
) -> list[tuple[str, str, str]]:
    """(资产类型, 名字, 图片) 按随请求上传的顺序排好、去重、截到上限；第 N 项就是参考图 N。

    场地的额外视角不占名字(名字为空)：正文里的 @[场地] 永远指它的主场景全景。
    """
    return [
        (item["kind"], "" if item.get("view") else item["name"], item["image_url"])
        for item in _ordered_references(sheets, references, limit=limit)
    ]


def _identity(item: Mapping[str, Any]) -> dict[str, Any]:
    """参考图来自素材库哪个元素的哪一版：资产改了之后，用过它的镜头和片段靠这个认出来。只在项目里的资产不带。"""
    element_id = _text(item.get("id"))
    if not element_id:
        return {}
    identity: dict[str, Any] = {"id": element_id, "version": item.get("version") if isinstance(item.get("version"), int) else 0}
    variant_id = _text(item.get("variant_element_id"))
    if variant_id:
        look = next((entry for entry in item.get("variants") or [] if isinstance(entry, Mapping) and _text(entry.get("id")) == variant_id), {})
        identity["variant_element_id"] = variant_id
        identity["variant_version"] = look.get("version") if isinstance(look.get("version"), int) else 0
    return identity


def panel_context(context: dict, shot: dict, *, layout: str = "", crowd: Iterable[str] = (), desk: bool = False) -> dict:
    """Respect the shot's cast column and bind references with type/name labels.

    ``layout`` is the set's screen sides from the spatial stage (门在画面右侧、窗在画面左侧); the
    scene reference states it, so the picture and the blocking agree on left and right. ``desk``: the
    shot carries a fresh director-desk still or blockout clip, so the scene plates give only materials,
    palette, light and period (see :func:`bind_scene_frames`).
    """
    action = _text(shot.get("desc"))
    if len(action) < 2 or _PLACEHOLDER.search(action):
        raise ValueError(_says("placeholder_shot"))
    aliases = context.get("cast_aliases") or {}
    declared = list(dict.fromkeys(aliases.get(name, name) for name in _names(shot.get("characters"))))
    unknown = [
        name
        for name in declared
        if name not in context["characters"] and name not in _EMPTY_NAMES and not _is_anonymous(name)
    ]
    unrelated = [
        name
        for name in context["all_character_names"]
        if name not in context["characters"] and _named(name, action, aliases)
    ]
    if unknown or unrelated:
        raise ValueError(_says("uncast_in_shot", names=_word("name_separator").join(unknown or unrelated)))
    if declared or shot.get("characters_explicit"):
        characters = [name for name in declared if name in context["characters"]]
        missing = [
            name
            for name in context["characters"]
            if _named(name, action, aliases) and name not in characters
        ]
        if missing:
            raise ValueError(_says("cast_column_missing", names=_word("name_separator").join(missing)))
    else:
        characters = [
            name for name in context["characters"] if _named(name, action, aliases)
        ] or context["characters"]
    selected = []
    for item in context["actors"]:
        if item["name"] not in characters:
            continue
        # One shot may call for another look than its scene (a flashback, a costume change).
        asked = character_variants.triggered(
            item.get("variants") or [], action,
            character_variants.episode_of(context["scene_id"]), character_variants.scene_of(context["scene_id"]),
        )
        if asked is not None and asked.get("id") != item.get("variant_element_id"):
            base = {
                **item, "description": item.get("base_description", item.get("description")),
                "image_url": item.get("base_image_url", item.get("image_url")), "face_url": item.get("base_face_url", item.get("face_url")),
            }
            item = character_variants.apply(base, asked)
        selected.append(item)
    selected += context["scenes"]
    props = [item for item in context["props"] if mentioned(item, action) or named_by_noun(item, action, context["props"])]
    products = [
        item for item in context.get("products", []) if mentioned(item, action) or named_by_noun(item, action, context.get("products", []))
    ]
    effects = [item for item in context["effects"] if mentioned(item, action) or named_by_noun(item, action, context["effects"])]
    # 「雷劫劈下」写的就是「九霄雷劫」：核心词只属于本场一个特效时也绑上。
    effects += wuxia_vfx.bound_by_term(context["effects"], action, [item["name"] for item in effects])
    costumes = [
        item
        for item in context["costumes"]
        if any(costume_owner(item, name) for name in characters)
        or mentioned(item, action)
    ]
    on_set = set(crowd)
    # 群演、车辆、特技、置景按动作里点到的名字绑；妆效只要这场戏提到了，就跟着它长在谁身上。
    named_on_set = [
        item for kind, key in breakdown_kinds.CATALOG_KEYS.items() for item in context.get(key, [])
        if mentioned(item, action) or named_by_noun(item, action, context.get(key, []))
        or (kind == "makeup" and any(costume_owner(item, name) for name in characters))
    ]
    # 本场在场的群演(见 crowd_on_set)：这一镜没点名也照样在背景里。
    crowd_only = [
        item for item in context.get(breakdown_kinds.CATALOG_KEYS["extra"], [])
        if item["name"] in on_set and item not in named_on_set
    ]
    # 九张的上限：动作里点到名的车辆、特技、置景、群演排在旧服装图前面(戏服已经画在定妆图上了)，
    # 没点名、只在背景里的群演排最后。
    selected += props + products + effects + named_on_set + costumes + crowd_only
    # 车辆、商品和道具一样是人会碰的物件：一起进本镜的物件清单(持有、接触、递接、账本都按它认)。
    vehicles = [item for item in named_on_set if item["kind"] == "vehicle"]
    references: list[dict[str, str]] = []
    seen_urls = set()
    # 配套画在一张图里的几样(「长剑」与「长剑剑鞘」)：两条各存了一份同一张图，本镜只发一次，那句职责写成配套图。
    sets: dict[str, dict[str, Any]] = {}
    for item in selected:
        url = item.get("image_url")
        members = drawn_set(item)
        if url and members and members[0] in sets:
            together = sets[members[0]]
            together["set"] = list(dict.fromkeys([*together["set"], *members]))
            together["used"] = list(dict.fromkeys([*together["used"], item["name"]]))
            continue
        if url and url not in seen_urls and len(references) < 9:
            reference = {"kind": item["kind"], "name": item["name"], "image_url": url, **_identity(item)}
            # 物件的真实大小跟着参考图走：设定图按多长画的，镜头里就按多长画，跟人同框不穿模、不失比例。
            if item["kind"] in OBJECT_KINDS and (size := real_size_note(item["kind"], item["name"], str(item.get("description") or ""), item.get("metadata"))):
                reference["size"] = size
            if item.get("variant"):
                reference["variant"] = str(item["variant"])
                # 定妆图上画了的妆效也写进提示词：图上左右画反了，按文字改回来。
                if worn := look_makeup(str(item.get("description") or "")):
                    reference["look_makeup"] = worn
                # 这一场按剧情穿的那身，衣服的文字跟着这张参考图一起进提示词。
                if outfit := look_outfit(str(item.get("description") or "")):
                    reference["outfit"] = outfit
                if item.get("variant_drawn") is False:
                    reference["look_undrawn"] = True
            if item["kind"] == "actor":
                # 没画进定妆图的妆效：这一镜提到它，就按文字加在当时那身上。
                added = [
                    _text(makeup.get("description")) or _text(makeup.get("name")) for makeup in context.get("makeup", [])
                    if not makeup.get("image_url") and mentioned(makeup, action) and costume_owner(makeup, item["name"])
                ]
                if added:
                    reference["makeup"] = _CLAUSE.join(added)
            if item["kind"] == "scene" and layout.strip():
                reference["layout"] = layout.strip()
            if item.get("real_person"):
                reference["real_person"] = True
                assets = real_person.ark_assets(item.get("metadata"))
                if assets:
                    reference["ark_assets"] = assets
            if members:
                reference["set"], reference["used"] = members, [item["name"]]
                sets[members[0]] = reference
            references.append(reference)
            seen_urls.add(url)
            # 正面大头照紧跟在这个人的正面全身照后面：全身照管体型、发型与服装，大头照管相貌。
            face_url = item.get("face_url")
            if item["kind"] == "actor" and face_url and face_url not in seen_urls and len(references) < 9:
                references.append({
                    "kind": "actor", "name": item["name"], "image_url": face_url, "view": "face",
                    **({"real_person": True} if item.get("real_person") else {}), **_identity(item),
                })
                seen_urls.add(face_url)
    # The set's extra views come last: they only take the places the cast and props leave free.
    # 只带这一镜定构图的那一张：用不上的视角图不发，免得它们的前景串进本镜。主场景全景照常发，核对陈设。
    # 一组正反打里的一镜：场地有反打视角、主场景全景也发出去了，就把反打视角配成一对(正面 + 反打)发。
    empty_shot = not any(item["kind"] == "actor" for item in references)
    exchange = in_exchange(shot, len(characters))
    for item in context["scenes"]:
        views = {view: url for view, url in (item.get("views") or {}).items() if view in SCENE_VIEW_PURPOSES and url}
        if exchange and views.get(SCENE_REVERSE_SLOT) and item.get("image_url") in seen_urls:
            chosen: str | None = SCENE_REVERSE_SLOT
        else:
            chosen = scene_frame_view(shot, {*views, *(["scene_main"] if item.get("image_url") else [])}, empty_shot=empty_shot)
        url = views.get(chosen or "")
        if chosen != "scene_main" and url and url not in seen_urls and len(references) < 9:
            references.append({"kind": "scene", "name": item["name"], "image_url": url, "view": chosen, **_identity(item)})
            seen_urls.add(url)
    bind_scene_frames(references, shot, empty_shot=empty_shot, desk=desk)
    return {
        "characters": characters or [EMPTY_ACTOR],
        "props": [item["name"] for item in (*props, *products, *vehicles)] or [_says("no_props")],
        "effects": [item["name"] for item in effects] or [_says("no_effects")],
        "references": references,
        "assets": [{"kind": item["kind"], "name": item["name"], "description": str(item.get("description") or "")} for item in selected],
    }
