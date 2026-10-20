# -*- coding: utf-8 -*-
"""Which kind of story this is, and what a storyboard for it needs.

Genres group into seven clusters, and the cluster — not the individual genre — is
what decides how a scene is shot: whether fight coverage is even in play, how fast
the default rhythm is, which feeling the brief falls back to when the director
names none, and which failure modes the negatives have to cover.

The genre is read from the story itself (the breakdown's own genre, the scene text,
the title) rather than from the title alone, because a title says very little.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.core.creative_intent import IntentPlan, decode


@dataclass(frozen=True)
class GenreCluster:
    id: str
    name: str
    keywords: tuple[str, ...]
    # The project's own genre keys (ModelGateway.get_genre) that belong here.
    genre_keys: tuple[str, ...]
    fight_coverage: bool           # fight staging is normal in this cluster
    default_intent: str            # the feeling a brief falls back to
    rhythm_profile: str            # the nine-grid rhythm label
    negative_modules: tuple[str, ...]
    note: str


CLUSTERS: tuple[GenreCluster, ...] = (
    GenreCluster(
        "A", "现代都市文戏",
        ("都市", "职场", "家庭", "伦理", "甜宠", "霸总", "校园", "婚姻", "商战", "医生", "律师", "重生复仇"),
        ("romance", "retro_romance", "campus", "family", "male_counterattack", "rebirth_revenge", "food", "interactive"),
        fight_coverage=False, default_intent="tension", rhythm_profile="confrontation",
        negative_modules=("performance_acting", "scene_layout_lighting"),
        note="靠表演与关系推进：过肩正反打、缓慢推近、微表情，运动镜头留给情绪转折。",
    ),
    GenreCluster(
        "B", "古装权谋江湖",
        ("古装", "宫廷", "权谋", "宅斗", "朝堂", "江湖", "武侠", "年代", "民国"),
        ("palace_intrigue", "wuxia"),
        fight_coverage=True, default_intent="tension", rhythm_profile="confrontation",
        negative_modules=("period_costume_architecture", "weapon_contact", "costume_hair_props"),
        note="服化道与礼制先立住；文戏靠站位与眼神，武戏才换打斗覆盖。",
    ),
    GenreCluster(
        "C", "仙侠玄幻修真",
        ("仙侠", "修仙", "玄幻", "灵气", "法术", "结界", "飞升", "妖", "神魔", "灵根"),
        ("xianxia",),
        fight_coverage=True, default_intent="burning", rhythm_profile="action",
        negative_modules=("action_physics", "material_texture", "period_costume_architecture"),
        note="法术要有蓄力→释放→命中→余波四拍；特效分层，别盖住人物。",
    ),
    GenreCluster(
        "D", "动作打斗战争",
        ("动作", "打斗", "格斗", "枪战", "军旅", "战争", "追车", "特工", "拳"),
        ("military", "sports", "mafia"),
        fight_coverage=True, default_intent="tight_fight", rhythm_profile="action",
        negative_modules=("action_physics", "weapon_contact", "crowd_limb_separation"),
        note="动作按起手→碰撞→结果拆镜，硬切落在撞击帧，空间单向推进。",
    ),
    GenreCluster(
        "E", "悬疑惊悚",
        ("悬疑", "惊悚", "恐怖", "刑侦", "灵异", "民俗", "密室", "凶案", "失踪"),
        ("mystery", "horror"),
        fight_coverage=False, default_intent="eerie", rhythm_profile="suspense",
        negative_modules=("suspense_horror_visibility", "scene_layout_lighting"),
        note="信息延后给出：遮挡、POV、物件插入；光只够看清该看的那一点。",
    ),
    GenreCluster(
        "F", "科幻末世机甲",
        ("科幻", "末世", "机甲", "赛博", "星际", "废土", "时空", "人工智能", "克隆"),
        ("time_travel", "alpha", "omega", "wolf", "vampire"),
        fight_coverage=True, default_intent="impact", rhythm_profile="action",
        negative_modules=("scifi_material_ui", "material_texture", "action_physics"),
        note="机械与界面要有材质与磨损；巨物用比例对比，不靠光效堆量。",
    ),
    GenreCluster(
        "G", "喜剧",
        ("喜剧", "搞笑", "沙雕", "无厘头", "情景", "爆笑", "吐槽"),
        ("comedy",),
        fight_coverage=False, default_intent="comedic", rhythm_profile="comedy",
        negative_modules=("performance_acting", "face_anatomy"),
        note="反应镜是正文：给足停顿与夸张表情，节奏靠剪辑不靠运镜。",
    ),
)
_BY_ID = {cluster.id: cluster for cluster in CLUSTERS}
_BY_GENRE_KEY = {key: cluster for cluster in CLUSTERS for key in cluster.genre_keys}
DEFAULT_CLUSTER_ID = "A"


def get_cluster(cluster_id: str) -> GenreCluster | None:
    return _BY_ID.get(str(cluster_id or "").strip().upper())


def cluster_for(genre: str = "", *, text: str = "") -> GenreCluster:
    """The cluster of a production: its genre key first, then the words of the story."""
    keyed = _BY_GENRE_KEY.get(str(genre or "").strip().lower())
    if keyed is not None:
        return keyed
    haystack = f"{genre} {text}"
    scored = [
        (sum(haystack.count(word) for word in cluster.keywords), cluster)
        for cluster in CLUSTERS
    ]
    best_score, best = max(scored, key=lambda item: (item[0], -CLUSTERS.index(item[1])))
    return best if best_score else _BY_ID[DEFAULT_CLUSTER_ID]


@dataclass
class DirectionPlan:
    """A cluster plus the decoded feeling: everything a scene's prompt needs up front."""

    cluster: GenreCluster
    intent: IntentPlan

    def brief(self) -> str:
        return "\n".join((
            f"【题材】{self.cluster.name}（{self.cluster.id}簇）：{self.cluster.note}",
            self.intent.brief(),
        ))

    def as_dict(self) -> dict:
        return {
            "cluster": self.cluster.id, "cluster_name": self.cluster.name,
            "fight_coverage": self.cluster.fight_coverage, "rhythm_profile": self.cluster.rhythm_profile,
            "negative_modules": list(self.cluster.negative_modules),
            "intent": self.intent.as_dict(),
        }


def plan_direction(
    *, genre: str = "", text: str = "", brief: str = "", primary: str = "", secondary: Sequence[str] = (),
) -> DirectionPlan:
    """Route the story to its cluster and decode the director's feeling inside it."""
    cluster = cluster_for(genre, text=text)
    intent = decode(brief or text, primary=primary, secondary=secondary, default=cluster.default_intent)
    return DirectionPlan(cluster=cluster, intent=intent)


def direction_from_task(config: Mapping[str, object], *, genre: str = "", text: str = "") -> DirectionPlan:
    """The direction of a task: its configured feeling, else the words of its brief and story."""
    guidance = " ".join(str(config.get(key) or "") for key in ("guidance_instruction", "title_suggestion"))
    return plan_direction(
        genre=genre, text=text, brief=guidance,
        primary=str(config.get("primary_intent") or ""),
        secondary=[item for item in (config.get("secondary_intents") or []) if isinstance(item, str)],
    )


def describe() -> list[dict]:
    return [
        {
            "id": cluster.id, "name": cluster.name, "keywords": list(cluster.keywords),
            "genre_keys": list(cluster.genre_keys), "fight_coverage": cluster.fight_coverage,
            "default_intent": cluster.default_intent, "rhythm_profile": cluster.rhythm_profile,
            "negative_modules": list(cluster.negative_modules), "note": cluster.note,
        }
        for cluster in CLUSTERS
    ]


__all__ = [
    "CLUSTERS", "DEFAULT_CLUSTER_ID", "DirectionPlan", "GenreCluster",
    "cluster_for", "describe", "direction_from_task", "get_cluster", "plan_direction",
]
