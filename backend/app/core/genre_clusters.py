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

from app.core import prompt_data
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


# The name, story keywords and staging note of each cluster: app/data/prompt/genre_clusters.json.
_WORDING = "genre_clusters"


def _says(key: str, /, **values: object) -> str:
    """A sentence of the clusters' wording table, filled in (``key`` is positional: a template may name a ``{key}``)."""
    return str(prompt_data.load(_WORDING)["says"][key]).format(**values)


def _cluster(
    cluster_id: str, genre_keys: tuple[str, ...], *, fight_coverage: bool, default_intent: str, rhythm_profile: str,
    negative_modules: tuple[str, ...],
) -> GenreCluster:
    """A cluster from its code values here and its words in the table (looked up by ``cluster_id``)."""
    words = prompt_data.load(_WORDING)["clusters"][cluster_id]
    return GenreCluster(
        cluster_id, str(words["name"]), tuple(str(word) for word in words["keywords"]), genre_keys,
        fight_coverage=fight_coverage, default_intent=default_intent, rhythm_profile=rhythm_profile,
        negative_modules=negative_modules, note=str(words["note"]),
    )


# Order matters: a keyword tie goes to the earlier cluster.
CLUSTERS: tuple[GenreCluster, ...] = (
    _cluster(
        "A", ("romance", "retro_romance", "campus", "family", "male_counterattack", "rebirth_revenge", "food", "interactive"),
        fight_coverage=False, default_intent="tension", rhythm_profile="confrontation",
        negative_modules=("performance_acting", "scene_layout_lighting"),
    ),
    _cluster(
        "B", ("palace_intrigue", "wuxia"),
        fight_coverage=True, default_intent="tension", rhythm_profile="confrontation",
        negative_modules=("period_costume_architecture", "weapon_contact", "costume_hair_props"),
    ),
    _cluster(
        "C", ("xianxia",),
        fight_coverage=True, default_intent="burning", rhythm_profile="action",
        negative_modules=("action_physics", "material_texture", "period_costume_architecture"),
    ),
    _cluster(
        "D", ("military", "sports", "mafia"),
        fight_coverage=True, default_intent="tight_fight", rhythm_profile="action",
        negative_modules=("action_physics", "weapon_contact", "crowd_limb_separation"),
    ),
    _cluster(
        "E", ("mystery", "horror"),
        fight_coverage=False, default_intent="eerie", rhythm_profile="suspense",
        negative_modules=("suspense_horror_visibility", "scene_layout_lighting"),
    ),
    _cluster(
        "F", ("time_travel", "alpha", "omega", "wolf", "vampire"),
        fight_coverage=True, default_intent="impact", rhythm_profile="action",
        negative_modules=("scifi_material_ui", "material_texture", "action_physics"),
    ),
    _cluster(
        "G", ("comedy",),
        fight_coverage=False, default_intent="comedic", rhythm_profile="comedy",
        negative_modules=("performance_acting", "face_anatomy"),
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

    def brief(self, scene_key: str = "") -> str:
        return "\n".join((
            _says("brief", name=self.cluster.name, id=self.cluster.id, note=self.cluster.note),
            self.intent.brief(scene_key),
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
