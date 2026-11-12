"""Scene-scoped production references; no provider calls or persistence."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from app.core import breakdown_kinds, character_variants, emotion_points, literary, prompt_data, prop_scale, real_person
from app.core.face_card import parse_face_card, render_face_card
from app.core import wuxia_vfx
from app.core.scene_turnaround import SCENE_REVERSE_SLOT, SCENE_VIEW_LABELS, SCENE_VIEW_PURPOSES

KINDS = {"scene": "scenes", "prop": "props", "costume": "costumes", "effect": "effects", "product": "products", **breakdown_kinds.CATALOG_KEYS}
LABELS = {
    "actor": "数字演员",
    "scene": "拍摄场地",
    "prop": "拍摄道具",
    "costume": "服装",
    "effect": "特效",
    "product": "商品",
    **breakdown_kinds.LABELS,
}
#: 妆效不在这里：只有一处伤的人，不等于每场都带着它，受伤之前的戏不能画上。
EMPTY_ACTOR = "空镜（无人物）"
_EMPTY_NAMES = {"无", "无人", "无人物", "空镜", "—", "-", "无出场角色", EMPTY_ACTOR}
# 剧本里没有名字的人(「一双粗手」「门外的人影」)：分镜表照实写成「未露面按压者」「画外声音」这类称呼，
# 它们不是编出来的新角色，也没有设定集可绑——不算未出场角色，也不进身份参考。
_ANONYMOUS = re.compile(r"^(?:未露面|不露脸|画外|无名|匿名|路人|群演|众人|某个?|一名|一位)")
# 只有身份、没有名字的跑龙套(「管事」「仆妇甲」「侍卫二」)：剧本按职务称呼他们，同样不是新角色。
# 带姓的「李管事」是有名有姓的人，不在此列，照常按角色核对。
_EXTRA_ROLE = re.compile(
    r"^(?:管事|管家|仆妇|仆役|仆人|仆从|下人|家丁|小厮|丫鬟|婢女|侍女|婆子|嬷嬷|侍卫|护卫|守卫|卫兵|士兵|兵丁|官兵|"
    r"衙役|差役|狱卒|太监|宫女|内侍|掌柜|伙计|小二|车夫|轿夫|马夫|百姓|村民|看客|宾客|食客|随从|跟班|杂役)"
    r"(?:[甲乙丙丁戊一二三四五六七八九十\d]{1,2}|们|等人)?$"
)


# 剧本里成片的人(「玄黑人影挤满石阶」「黑衣人」「阶下众人」)：分镜照剧本写进入镜列，是布景不是角色。
# 「演武场弟子」「外门弟子们」是一群没有名字的人；剧本里有名有姓的弟子在角色表里，不走这里。
_CROWD = re.compile(r"(?:人影|身影|黑影|剪影|人群|众人|之人|的人|来人|来者)$|^.{0,3}(?:衣人|蒙面人|蒙面者)$|(?:弟子|门人|门徒)们?$")


def _is_anonymous(name: str) -> bool:
    return bool(_ANONYMOUS.match(name) or _EXTRA_ROLE.match(name) or _CROWD.search(name))


def is_uncast(name: str) -> bool:
    """空镜标记、无名路人和按职务称呼的跑龙套：不是角色，没有设定集要绑。"""
    name = _text(name)
    return not name or name in _EMPTY_NAMES or _is_anonymous(name)


# 「女配角」「反派」是戏份，不是称呼，好几个人共用，不能拿来认人。
_BILLING = re.compile(r"^(?:[男女]?(?:主角|配角|主|配|一号|二号|三号)|反派|大?反派|主要?角色|次要角色|龙套|群演|客串|特约)$")


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
        title = re.sub(r"[（(][^）)]*[）)]", "", _text(title)).strip()
        if 2 <= len(title) <= 12 and title != name and not _BILLING.match(title) and not is_uncast(title):
            found.setdefault(title, set()).add(name)

    for item in people:
        name = _text(item["name"])
        head = re.split(r"[；;。\n]", _text(item.get("desc")), maxsplit=1)[0]
        if len(head) <= 40:
            for title in re.split(r"[／/、，,|]", head):
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
        text = re.sub(rf"(?<![（(@\[]){re.escape(title)}(?![）)\]])", f"@[{owner}]", text)
    return text


def _named(name: str, text: str, aliases: dict[str, str]) -> bool:
    """正文点到这个人：叫名字，或叫他的称呼。"""
    return name in text or any(owner == name and title in text for title, owner in aliases.items())


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _names(value: Any) -> list[str]:
    if isinstance(value, str):
        value = re.split(r"[、，,/]", value)
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


def mentioned(item: dict, text: str) -> bool:
    name = _text(item.get("name"))
    aliases = _names(item.get("aliases")) + _names(name)
    # Catalog labels commonly append staging annotations to the actual name.
    stem = re.split(r"[（(]", name)[0]
    stem = re.sub(r"(?:夜景|日景|内景|外景|全景|场景|效果|特效)$", "", stem)
    # A label such as 血痕三道 names the same effect as 三道血痕.
    stem = re.sub(r"[一二三四五六七八九十百\d]+(?:道|条|滴|束)", "", stem)
    # 「沈砚·额角刀伤」: the script says 额角刀伤, not the whole label.
    tail = stem.rsplit("·", 1)[-1]
    return any(len(alias) >= 2 and alias in text for alias in [name, stem, tail, *aliases])


def _line(item: dict) -> str:
    return f"{item['name']}：{item.get('description') or '沿用已确认造型与状态'}"


def costume_owner(item: dict, name: str) -> bool:
    # '贺兰霆亲卫' and '贺兰霆手下' describe other actors, not his outfit.
    return name in item["name"] or bool(
        re.match(
            rf"^{re.escape(name)}(?:[，,：:；;\s]|$)", _text(item.get("description"))
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
        f"\n对白：{dialogue}" if dialogue and dialogue not in {"-", "—", "无"} else ""
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
            matched = bool(explicit_scope) or mentioned(item, script)
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
        f"【当前剧情 {scene_id}】\n{script}",
        "以下资料只用于锁定外观；不得把资产背景故事或其他场次事件画进本场。",
    ]
    for kind, items in [
        ("actor", actors),
        *((kind, context[key]) for kind, key in KINDS.items()),
    ]:
        lines.append(
            f"【{LABELS[kind]}】\n"
            + (
                "\n".join(_line(item) for item in items)
                or "无已匹配资产；仅依据当前剧情，不添加无关内容"
            )
        )
    context["prompt"] = "\n".join(lines)
    return context


def look_makeup(description: str) -> str:
    """一身妆造(或穿着它的角色设定)里的妆效文字；没写妆效时是空串。"""
    _before, marker, after = str(description or "").partition("妆效：")
    return after.strip(" ；;。") if marker else ""


def look_outfit(description: str) -> str:
    """穿着妆造的角色设定里那身衣服的文字(「服装：」到「妆效：」之间)；没写时是空串。"""
    _before, marker, after = str(description or "").partition("服装：")
    return after.split("妆效：")[0].strip(" ；;。") if marker else ""


def look_makeup_note(makeup: str, *, panel: bool = False) -> str:
    """跟在参考图那句后面的妆效：定妆图把左右画反了，也按文字画。句中不用「；」「。」。措辞在 character_looks.json。"""
    text = re.sub(r"[；;。]+", "，", str(makeup or "")).strip("，")
    return prompt_data.text("character_looks", "panel_look_makeup" if panel else "shot_look_makeup").format(text) if text else ""


def look_outfit_note(name: str, variant: str, outfit: str, *, drawn: bool = True) -> str:
    """跟在参考图那句后面：这个人这一镜按剧情穿的那身是什么。还没画成定妆图时写明衣服只按文字。

    句中不用「；」「。」，参考图被路由去掉时这句留下，衣服的文字照样在提示词里。措辞在 character_looks.json。
    """
    text = re.sub(r"[；;。]+", "，", str(outfit or "")).strip("，")[: prompt_data.number("character_looks", "outfit_limit")]
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
        face = render_face_card(card, include_other=False) if card.has_face_layers else str(dressed[name] or "").strip("；;。 ")
        dressed[name] = "；".join(part for part in (face, f"服装：{outfit}") if part)
    return dressed


def real_size_note(kind: str, name: str) -> str:
    """道具和车辆在参照表里的真实尺寸，跟在参考图那句后面；查不到是空串。句中不用「；」「。」。"""
    if kind not in ("prop", "vehicle"):
        return ""
    scale = prop_scale.lookup(name)
    return prompt_data.text("prop_scale", "reference_size").format(scale.size_text()) if scale is not None else ""


def reference_note(number: int, reference: dict, *, label: str = "") -> str:
    """参考图N 只锁一件资产的那句话。

    场地图写明它锁的是空间：布局事实(门在画面左侧、窗在画面右侧)，图中人物不作参考；场地设定图
    只有一种天色，光线与时段以本场为准——雨夜戏照着白天的场地图画，会画成阴天白天；
    场地的额外视角(45°、纵深、细节)写明各自用来做什么。句中不出现「；」「。」，
    这样 ``video_references.renumber_reference_mentions`` 能整句改号或整句删掉。
    """
    kind, name = str(reference.get("kind") or ""), str(reference.get("name") or "")
    label = label or LABELS.get(kind, kind)
    if kind in breakdown_kinds.KINDS:
        return breakdown_kinds.reference_note(number, kind, name) + real_size_note(kind, name)
    if kind == "actor" and reference.get("real_person") and reference.get("view") == "face":
        outfit = re.sub(r"[；;。]+", "，", str(reference.get("outfit") or "")).strip("，")
        variant = re.sub(r"[；;。]+", "，", str(reference.get("variant") or "")).strip("，")
        return (
            real_person.say("reference_face", number, name)
            + (real_person.say("outfit_by_text", variant or "本场造型", outfit) if outfit else "")
            + look_makeup_note(str(reference.get("look_makeup") or ""))
        )
    if kind == "actor" and reference.get("view") == "face":
        return prompt_data.text("character_looks", "shot_headshot").format(number, label, name)
    if kind == "actor":
        variant = re.sub(r"[；;。]+", "，", str(reference.get("variant") or "")).strip("，")
        makeup = re.sub(r"[；;。]+", "，", str(reference.get("makeup") or "")).strip("，")
        outfit = look_outfit_note(name, variant, str(reference.get("outfit") or ""), drawn=not reference.get("look_undrawn"))
        if variant and reference.get("look_undrawn"):
            lead = prompt_data.text("character_looks", "shot_look_undrawn").format(number, label, name)
        else:
            lead = f"参考图{number}仅锁定{label}「{name}」{f'（造型：{variant}）' if variant else ''}的脸型、发型、体型与服装，不采用图中背景、版式与其他人物，不是额外剧情或额外人物"
        return (
            lead + outfit
            + look_makeup_note(str(reference.get("look_makeup") or ""))
            + (real_person.say("reference_body") if reference.get("real_person") else "")
            + (f"，图上没有的妆效按文字加上：{makeup}" if makeup else "")
        )
    if kind != "scene":
        # 特效图只是一瞬：写明它在镜头里什么时候出现、怎么照人(措辞在 wuxia_vfx.json)。
        timing = prompt_data.text("wuxia_vfx", "shot_effect_reference") if kind == "effect" else ""
        return f"参考图{number}仅锁定{label}「{name}」的外形、材质与颜色，不采用图中背景与人物，不是额外剧情或额外人物" + timing + real_size_note(kind, name)
    view = str(reference.get("view") or "")
    layout = re.sub(r"[；;。]+", "，", _text(reference.get("layout"))).strip("，")
    frame = str(reference.get("frame") or "")
    # 只核对陈设的视角图不再写它平时用来做什么(「用于走位透视」)，免得和「不决定本镜构图」打架。
    purpose = "" if frame in ("space_only", "reverse") else f"，用于{SCENE_VIEW_PURPOSES.get(view, '')}"
    scope = (
        f"的{SCENE_VIEW_LABELS[view]}{purpose}"
        if view in SCENE_VIEW_PURPOSES and view != "scene_main"
        else "的空间布局，光线与天色以本场为准、不照搬此图"
    )
    return (
        f"参考图{number}仅锁定{label}「{name}」{scope}"
        + (f"（{layout}）" if layout else "")
        + (prompt_data.text("scene_views", frame) if frame else "")
        + "，图中人物不作参考，不是额外剧情或额外人物"
    )


def scene_frame_view(shot: Mapping[str, Any], available: set[str], *, empty_shot: bool) -> str | None:
    """这一镜用场地的哪张视角图定构图；反打镜头没有反打视角时返回 None(没有一张对得上方向)。

    按景别、角度、运镜的关键词挑，挑中的视角没有就退回主场景全景；细节图只给无人的插入镜头。
    关键词在 scene_views.json。
    """
    framing = " ".join(_text(shot.get(key)) for key in ("size", "angle", "motion", "framing"))
    if any(word in framing for word in prompt_data.words("scene_views", "reverse_words")):
        return SCENE_REVERSE_SLOT if SCENE_REVERSE_SLOT in available else None
    fallback = "scene_main" if "scene_main" in available else next(iter(sorted(available)), None)
    return next(
        (
            view for view, words in prompt_data.value("scene_views", "pick")
            if view in available and (view != "scene_detail" or empty_shot) and any(word in framing for word in words)
        ),
        fallback,
    )


def bind_scene_frames(references: list[dict], shot: Mapping[str, Any], *, empty_shot: bool) -> None:
    """同一场地发了几张视角图时，给每张写明这一镜里的职责(``frame``)。

    几张图不分职责一起发，模型会把另一个方向的前景(反向那张图里的台阶、门)混进本镜。一张是本镜唯一的
    场景构图来源，其余只核对陈设；反打镜头没有反打视角时，全部只核对陈设、写明方向相反。
    """
    scenes = [item for item in references if item.get("kind") == "scene"]
    for name in dict.fromkeys(str(item.get("name") or "") for item in scenes):
        group = [item for item in scenes if item.get("name") == name]
        chosen = scene_frame_view(shot, {str(item.get("view") or "scene_main") for item in group}, empty_shot=empty_shot)
        if chosen is None:
            for item in group:
                item["frame"] = "reverse"
        elif len(group) > 1:
            for item in group:
                item["frame"] = "composition" if str(item.get("view") or "scene_main") == chosen else "space_only"


def _crowd_moves(item: dict, text: str, key: str) -> bool:
    """这段文字里，这批群演的名字后面不远处有没有进场 / 离场的词。"""
    name = _text(item.get("name"))
    stem = re.split(r"[（(]", name)[0]
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
        prompt_data.text("crowd_presence", "shot_line").format(item["name"], _text(item.get("description")) or "沿用本场人数与站位")
        for item in context.get("extras") or [] if item["name"] in names and not mentioned(item, action)
    ]


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
        reference_note(number, item, label="数字演员设定集" if item["kind"] == "actor" else "")
        for number, item in enumerate(entries, start=1)
    ]
    return images, "；".join(notes)


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


def panel_context(context: dict, shot: dict, *, layout: str = "", crowd: Iterable[str] = ()) -> dict:
    """Respect the shot's cast column and bind references with type/name labels.

    ``layout`` is the set's screen sides from the spatial stage (门在画面右侧、窗在画面左侧); the
    scene reference states it, so the picture and the blocking agree on left and right.
    """
    action = _text(shot.get("desc"))
    if len(action) < 2 or re.search(
        r"剧情推进分镜\s*\d+|第\d+个因果/情绪信息单元", action
    ):
        raise ValueError("分镜画面仍为通用占位内容，请重新拆解当前剧情")
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
        raise ValueError(
            "分镜包含当前剧情未出场角色：" + "、".join(unknown or unrelated)
        )
    if declared or shot.get("characters_explicit"):
        characters = [name for name in declared if name in context["characters"]]
        missing = [
            name
            for name in context["characters"]
            if _named(name, action, aliases) and name not in characters
        ]
        if missing:
            raise ValueError("分镜画面与入镜角色列不一致，缺少：" + "、".join(missing))
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
    props = [item for item in context["props"] if mentioned(item, action)]
    products = [item for item in context.get("products", []) if mentioned(item, action)]
    effects = [item for item in context["effects"] if mentioned(item, action)]
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
    extras_on_set = [
        item for kind, key in breakdown_kinds.CATALOG_KEYS.items() for item in context.get(key, [])
        if mentioned(item, action) or (kind == "makeup" and any(costume_owner(item, name) for name in characters))
        # 本场在场的群演(见 crowd_on_set)：这一镜没点名也照样在背景里。
        or (kind == "extra" and item["name"] in on_set)
    ]
    # 特效图排在旧服装图前面：九张的上限先让给特效(戏服已经画在定妆图上了)。
    selected += props + products + effects + costumes + extras_on_set
    references: list[dict[str, str]] = []
    seen_urls = set()
    for item in selected:
        url = item.get("image_url")
        if url and url not in seen_urls and len(references) < 9:
            reference = {"kind": item["kind"], "name": item["name"], "image_url": url, **_identity(item)}
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
                    reference["makeup"] = "，".join(added)
            if item["kind"] == "scene" and layout.strip():
                reference["layout"] = layout.strip()
            if item.get("real_person"):
                reference["real_person"] = True
                assets = real_person.ark_assets(item.get("metadata"))
                if assets:
                    reference["ark_assets"] = assets
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
    empty_shot = not any(item["kind"] == "actor" for item in references)
    for item in context["scenes"]:
        views = {view: url for view, url in (item.get("views") or {}).items() if view in SCENE_VIEW_PURPOSES and url}
        chosen = scene_frame_view(shot, {*views, *(["scene_main"] if item.get("image_url") else [])}, empty_shot=empty_shot)
        url = views.get(chosen or "")
        if chosen != "scene_main" and url and url not in seen_urls and len(references) < 9:
            references.append({"kind": "scene", "name": item["name"], "image_url": url, "view": chosen, **_identity(item)})
            seen_urls.add(url)
    bind_scene_frames(references, shot, empty_shot=empty_shot)
    return {
        "characters": characters or [EMPTY_ACTOR],
        "props": [item["name"] for item in props] or ["本格无额外道具"],
        "effects": [item["name"] for item in effects] or ["本格无额外特效"],
        "references": references,
        "assets": [{"kind": item["kind"], "name": item["name"], "description": str(item.get("description") or "")} for item in selected],
    }
