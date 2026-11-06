# -*- coding: utf-8 -*-
"""镜头衔接：接动作、接光线、接色调。

几段视频单看都好，连起来却"散"，多半是生成时就埋下的：光源方向一镜一变、色调一镜一变、
动作在完成之后才切。这里把三件事落到流水线上：

* **光线词固定**：同一场戏的每一镜都写同一句光线词。光线词从这场戏第一镜(建立镜)的分镜描述里
  原样摘出——主光方向、光源、色温、光比、时段天气——不编新内容；摘不到时沿用原来的锁定句。
* **基调词统一**：全片同一条调性。类型调性按整部戏的类型聚类(古装权谋江湖、现代都市文戏……)，
  不再套风格包的「都市剧情调性」；新建项目默认的「cyberpunk」与类型冲突时不写进提示词。
* **首尾帧接力**：一个分镜片段太长、被切成几段生成时，后一段以前一段的最后一帧开场，
  动作、光线、色调都从同一张画面接下去。

本模块只做规划与拼装：不调供应商、不写任务。
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from app.core import prompt_data
from app.core.genre_clusters import CLUSTERS, GenreCluster, cluster_for, get_cluster

#: 说光的结构的词：出现一个就算在说光。
_LIGHT_STRUCTURE = re.compile(r"主光|光源|光比|色温|侧逆光|逆光|侧光|顶光|底光|轮廓光|补光|明暗交界")
#: 具体的光：要和方向一起出现(「冷青天光自右前方」)才算在定光，单说「在冷光里」是在写物件。
_LIGHT_NOUN = re.compile(r"硬光|柔光|暖光|冷光|天光|月光|日光|晨光|夕照|火光|烛光|灯光|白光|橙光|青光")
_DIRECTION = re.compile(r"画面[左右上下]|[左右][上下前后]方|[左右]侧|高处|低位|斜|自|从|来自")
#: 这些分句说的是机位、构图或人物动作，不是光——即使顺带提到了光。
_NOT_LIGHT = re.compile(r"镜头|机位|推近|拉远|摇|跟拍|景别|构图|转身|抬手|握|看向|视线|拇指|扳指|刀背")
_CLAUSE = re.compile(r"[^，,。；;！？!?\n]+")
#: 光线词最长多少字(写进每一镜的锁定行，要短)。
MAX_LIGHT_CHARS = 90
#: 光线词最多取几个分句。
MAX_LIGHT_CLAUSES = 4


def light_phrase(text: str) -> str:
    """从一段分镜描述里原样摘出说光的分句，拼成一句光线词；摘不到返回空串。"""
    picked: list[str] = []
    for clause in _CLAUSE.findall(str(text or "")):
        clause = clause.strip()
        if not clause or _NOT_LIGHT.search(clause):
            continue
        if not (_LIGHT_STRUCTURE.search(clause) or (_LIGHT_NOUN.search(clause) and _DIRECTION.search(clause))):
            continue
        if clause in picked:
            continue
        if len("，".join([*picked, clause])) > MAX_LIGHT_CHARS:
            break
        picked.append(clause)
        if len(picked) >= MAX_LIGHT_CLAUSES:
            break
    return "，".join(picked)


def scene_light_phrases(shots: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """每场戏一句光线词：取这场戏里第一个能摘出光线的镜头(通常是建立镜)。"""
    phrases: dict[str, str] = {}
    for shot in shots:
        scene_id = str(shot.get("scene_id") or "")
        if not scene_id or scene_id in phrases:
            continue
        phrase = light_phrase(str(shot.get("desc") or ""))
        if phrase:
            phrases[scene_id] = phrase
    return phrases


#: 分场标题里说时段天气的词(「演武场 雨夜 外景」里的「雨夜」)：整词匹配，「雨夜长街」这种地名不算。
_TIME_TOKEN = re.compile(r"[雨雪风]?[深入午]?夜|白日|白天|日间|[清早]晨|黎明|拂晓|黄昏|傍晚|日暮|正午|午后")
#: 分镜帧的灯光行没有可写的时段与主光时沿用的说法。
DEFAULT_BOARD_LIGHTING = prompt_data.text("clip_prompt", "default_board_lighting")


def scene_time(heading: str) -> str:
    """分场标题(「地点 [子地点] 时段 内/外景 …」)里的时段天气与内外景，如「雨夜，外景」；没有时为空串。"""
    tokens = str(heading or "").split()[:6]
    when = [token for token in tokens if _TIME_TOKEN.fullmatch(token)]
    setting = [token for token in tokens if token in ("内景", "外景")][:1]
    return "，".join([*dict.fromkeys(when), *setting]) if when else ""


def board_lighting(heading: str, light: str = "") -> str:
    """分镜帧的灯光行：写明本场时段天气和建立镜定下的主光。

    分镜帧逐格生图，只有建立镜的描述里写了「雨夜」；后面的格子若只说「火把橙光」，
    再碰上白天口吻的场地设定(「开阔顶光」)，就会被画成阴天或白天，同一场戏前后光线对不上。
    """
    when = scene_time(heading)
    parts = []
    if when:
        night = "，是夜景，不得画成白天或阴天的天光" if "夜" in when else ""
        parts.append(f"本场时段天气：{when}，全场每一格保持同一时段与天色{night}")
    if light:
        parts.append(f"主光：{light}")
    return "；".join(parts) + "；人物脸部保持自然层次" if parts else DEFAULT_BOARD_LIGHTING


def scene_ref_slots(entries: Sequence[Sequence[Any]]) -> list[tuple[int, str]]:
    """参考图列表里场地图的位置与所属场地名：(序号, 场地)。场地的额外视角跟着前面的主场景图。"""
    slots: list[tuple[int, str]] = []
    current = ""
    for index, entry in enumerate(entries):
        if entry and entry[0] == "scene":
            current = str(entry[1] or "") or current
            if current:
                slots.append((index, current))
    return slots


def stand_in_clips(
    clips: Sequence[Mapping[str, Any]], headings: Mapping[str, str], scene_id: str, location: str, count: int,
) -> list[str]:
    """同一场地、同一时段已拍好的片段，离本场最近的排前：分镜帧被供应商拒收时拿它们的画面顶替场地设定图。

    场地设定图只有一种天色(多半是白天)；分镜帧被判敏感、只剩设定图可参考时，雨夜戏会被拍成白天。
    同场地同时段的成片画面带着本场该有的天色。自己这一场、被拒收后才拍成的片段(天色可能已经错了)不用。
    """
    wanted = scene_time(headings.get(scene_id, ""))
    if not wanted or count <= 0:
        return []
    order = {sid: index for index, sid in enumerate(headings)}
    here = order.get(scene_id, 0)
    picked = [
        clip for clip in clips
        if isinstance(clip, Mapping) and clip.get("video_url") and str(clip.get("scene_id") or "") != scene_id
        and not clip.get("stale") and not clip.get("moderation_fallback")
        and (clip.get("mention_kinds") or {}).get(location) == "scene"
        and scene_time(headings.get(str(clip.get("scene_id") or ""), "")) == wanted
    ]
    picked.sort(key=lambda clip: abs(order.get(str(clip.get("scene_id") or ""), here) - here))
    return list(dict.fromkeys(str(clip["video_url"]) for clip in picked))[:count]


def show_cluster(task: Mapping[str, Any], *, genre: str = "") -> GenreCluster:
    """整部戏的类型聚类：各场分镜规划时定下的聚类取多数；还没有分镜时按题材与标题判断。"""
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    boards = assets.get("4_scene_boards") if isinstance(assets.get("4_scene_boards"), Mapping) else {}
    votes = Counter(
        str((board.get("direction") or {}).get("cluster") or "")
        for board in boards.values()
        if isinstance(board, Mapping) and isinstance(board.get("direction"), Mapping)
    )
    votes.pop("", None)
    if votes:
        found = get_cluster(votes.most_common(1)[0][0])
        if found is not None:
            return found
    config = task.get("config") if isinstance(task.get("config"), Mapping) else {}
    return cluster_for(genre, text=str(config.get("title_suggestion") or ""))


#: 只适合某些类型的导演风格：写进别的类型的提示词里只会把画面带偏(武侠雨夜被写成赛博朋克)。
_STYLE_CLUSTERS: dict[str, frozenset[str]] = {
    "cyberpunk": frozenset({"F"}),
    "sci_fi_future": frozenset({"F"}),
}
FALLBACK_DIRECTOR_STYLE = prompt_data.text("clip_prompt", "fallback_director_style")


def coherent_director_style(style: str, cluster_id: str) -> str:
    """导演风格与整部戏的类型对得上就用它；对不上(如古装武侠配 cyberpunk)用真人电影写实。"""
    value = str(style or "").strip()
    allowed = _STYLE_CLUSTERS.get(value.lower())
    if allowed is not None and cluster_id not in allowed:
        return FALLBACK_DIRECTOR_STYLE
    return value or FALLBACK_DIRECTOR_STYLE


FIGHT_TEMPO = prompt_data.text("clip_prompt", "fight_tempo")


def tone_for(pack: Any, cluster: GenreCluster | None, *, fight: bool = False) -> str:
    """全片同一条调性：风格包的类型调性槽填整部戏的类型，其余槽用风格包默认值。

    ``fight`` 的场次把节奏槽换成打斗节奏——权谋戏的「稳健节奏」压在一场拳脚上，模型会把打斗拍成慢动作。
    """
    default = str(getattr(pack, "tone_default", "") or "")
    slots = list(getattr(pack, "tone_slots", []) or [])
    parts = [part.strip() for part in default.split("+")]
    if cluster is not None and slots and slots[0] == "类型调性":
        genre_tone = f"{cluster.name}调性"
        if parts and parts[0]:
            parts[0] = genre_tone
        else:
            parts = [genre_tone, *parts[1:]]
    if fight:
        tempo = next((index for index, slot in enumerate(slots) if "节奏" in slot), -1)
        if 0 <= tempo < len(parts):
            parts[tempo] = FIGHT_TEMPO
        elif tempo >= 0:
            parts.append(FIGHT_TEMPO)
    return " + ".join(part for part in parts if part)


def chained_fingerprint(own: str, parent: str) -> str:
    """接力段的请求指纹：前一段换了，后一段的开场画面也换了，旧片不能当同一请求复用。"""
    return "slice:" + hashlib.sha256(f"{parent}|{own}".encode("utf-8")).hexdigest()


__all__ = [
    "CLUSTERS", "DEFAULT_BOARD_LIGHTING", "FALLBACK_DIRECTOR_STYLE", "MAX_LIGHT_CHARS", "board_lighting",
    "FIGHT_TEMPO", "chained_fingerprint", "coherent_director_style", "light_phrase", "scene_light_phrases", "scene_ref_slots",
    "scene_time", "show_cluster", "stand_in_clips", "tone_for",
]
