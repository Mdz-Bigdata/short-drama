"""Scene-scoped production references; no provider calls or persistence."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from app.core import breakdown_kinds, character_variants, emotion_points, literary, prompt_data, prop_scale
from app.core.scene_turnaround import SCENE_VIEW_LABELS, SCENE_VIEW_PURPOSES

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


def look_makeup_note(makeup: str, *, panel: bool = False) -> str:
    """跟在参考图那句后面的妆效：定妆图把左右画反了，也按文字画。句中不用「；」「。」。措辞在 character_looks.json。"""
    text = re.sub(r"[；;。]+", "，", str(makeup or "")).strip("，")
    return prompt_data.text("character_looks", "panel_look_makeup" if panel else "shot_look_makeup").format(text) if text else ""


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
    if kind == "actor":
        variant = re.sub(r"[；;。]+", "，", str(reference.get("variant") or "")).strip("，")
        makeup = re.sub(r"[；;。]+", "，", str(reference.get("makeup") or "")).strip("，")
        return (
            f"参考图{number}仅锁定{label}「{name}」{f'（造型：{variant}）' if variant else ''}的脸型、发型、体型与服装，不采用图中背景、版式与其他人物，不是额外剧情或额外人物"
            + look_makeup_note(str(reference.get("look_makeup") or ""))
            + (f"，图上没有的妆效按文字加上：{makeup}" if makeup else "")
        )
    if kind != "scene":
        return f"参考图{number}仅锁定{label}「{name}」的外形、材质与颜色，不采用图中背景与人物，不是额外剧情或额外人物" + real_size_note(kind, name)
    view = str(reference.get("view") or "")
    layout = re.sub(r"[；;。]+", "，", _text(reference.get("layout"))).strip("，")
    scope = (
        f"的{SCENE_VIEW_LABELS[view]}，用于{SCENE_VIEW_PURPOSES[view]}"
        if view in SCENE_VIEW_PURPOSES and view != "scene_main"
        else "的空间布局，光线与天色以本场为准、不照搬此图"
    )
    return (
        f"参考图{number}仅锁定{label}「{name}」{scope}"
        + (f"（{layout}）" if layout else "")
        + "，图中人物不作参考，不是额外剧情或额外人物"
    )


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


def panel_context(context: dict, shot: dict, *, layout: str = "") -> dict:
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
            base = {**item, "description": item.get("base_description", item.get("description")), "image_url": item.get("base_image_url", item.get("image_url"))}
            item = character_variants.apply(base, asked)
        selected.append(item)
    selected += context["scenes"]
    props = [item for item in context["props"] if mentioned(item, action)]
    products = [item for item in context.get("products", []) if mentioned(item, action)]
    effects = [item for item in context["effects"] if mentioned(item, action)]
    costumes = [
        item
        for item in context["costumes"]
        if any(costume_owner(item, name) for name in characters)
        or mentioned(item, action)
    ]
    # 群演、车辆、特技、置景按动作里点到的名字绑；妆效只要这场戏提到了，就跟着它长在谁身上。
    extras_on_set = [
        item for kind, key in breakdown_kinds.CATALOG_KEYS.items() for item in context.get(key, [])
        if mentioned(item, action) or (kind == "makeup" and any(costume_owner(item, name) for name in characters))
    ]
    selected += props + products + costumes + effects + extras_on_set
    references: list[dict[str, str]] = []
    seen_urls = set()
    for item in selected:
        url = item.get("image_url")
        if url and url not in seen_urls and len(references) < 9:
            reference = {"kind": item["kind"], "name": item["name"], "image_url": url}
            if item.get("variant"):
                reference["variant"] = str(item["variant"])
                # 定妆图上画了的妆效也写进提示词：图上左右画反了，按文字改回来。
                if worn := look_makeup(str(item.get("description") or "")):
                    reference["look_makeup"] = worn
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
            references.append(reference)
            seen_urls.add(url)
    # The set's extra views come last: they only take the places the cast and props leave free.
    for item in context["scenes"]:
        for view, url in (item.get("views") or {}).items():
            if view in SCENE_VIEW_PURPOSES and url and url not in seen_urls and len(references) < 9:
                references.append({"kind": "scene", "name": item["name"], "image_url": url, "view": view})
                seen_urls.add(url)
    return {
        "characters": characters or [EMPTY_ACTOR],
        "props": [item["name"] for item in props] or ["本格无额外道具"],
        "effects": [item["name"] for item in effects] or ["本格无额外特效"],
        "references": references,
        "assets": [{"kind": item["kind"], "name": item["name"], "description": str(item.get("description") or "")} for item in selected],
    }
