"""An asset's name is its identity; renaming and merging follow every reference.

A character, scene or prop has no id of its own: its name is how the script
plan, the breakdown, the sheets and the shots all point at it. So a rename is
one atomic cascade over every place the name appears, and merging two assets
re-points the loser's references at the survivor and keeps the loser's name as
an alias, so planning still recognises it in the source text. Both operations
first produce a preview that counts what would change and what would go stale.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass, field
from typing import Any, Literal

from app.core import episode_cycle
from app.core.screenwriting.speech import is_narrator
from app.core import prompt_data


_WORDING_FILE = "asset_identity"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/asset_identity.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)

AssetKind = Literal["character", "scene", "prop"]
ASSET_KINDS: tuple[str, ...] = ("character", "scene", "prop")
STATE_KEY = "2_screenwriting"

_INVENTORY_BUCKET = {"character": "characters", "scene": "scenes", "prop": "props"}
_PLAN_LIST = {"character": "characters_in_scene", "scene": "scenes", "prop": "props"}
_BREAKDOWN_ASSET_KIND = {"scene": "scenes", "prop": "props"}
# The kind a storyboard binding (``shot["asset_bindings"]``) and the element library use for each identity kind.
_BINDING_KIND = {"character": "actor", "scene": "scene", "prop": "prop"}


class AssetIdentityError(ValueError):
    """The request names something that is not there, or a name that is taken."""


def canonical_name(value: object) -> str:
    """Names compare after trimming and Unicode normalisation; ``沈 知微`` and ``沈知微`` are not two people."""
    return unicodedata.normalize("NFC", str(value or "")).strip()


@dataclass
class IdentityImpact:
    kind: str
    name: str
    new_name: str
    references: dict[str, int] = field(default_factory=dict)
    episodes: list[int] = field(default_factory=list)
    stale_shots: list[int] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)

    def total(self) -> int:
        return sum(self.references.values())

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "name": self.name, "new_name": self.new_name,
            "references": dict(self.references), "total_references": self.total(),
            "episodes": list(self.episodes), "stale_shots": list(self.stale_shots), "aliases": list(self.aliases),
        }


def _state(task: Mapping[str, Any]) -> MutableMapping[str, Any] | None:
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    state = assets.get(STATE_KEY)
    return state if isinstance(state, MutableMapping) else None


def _inventory(task: Mapping[str, Any], kind: str) -> MutableMapping[str, Any]:
    state = _state(task)
    if state is None:
        return {}
    inventory = state.get("inventory")
    if not isinstance(inventory, MutableMapping):
        return {}
    bucket = inventory.get(_INVENTORY_BUCKET[kind])
    return bucket if isinstance(bucket, MutableMapping) else {}


def known_names(task: Mapping[str, Any], kind: str) -> list[str]:
    """Every name the project uses for assets of ``kind``, from the inventory, the breakdown and the sheets."""
    names: list[str] = []

    def add(value: object) -> None:
        clean = canonical_name(value)
        if clean and clean not in names:
            names.append(clean)

    for name in _inventory(task, kind):
        add(name)
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    breakdown = assets.get("2_breakdown") if isinstance(assets.get("2_breakdown"), Mapping) else {}
    if kind == "character":
        for role in breakdown.get("roles") or []:
            if isinstance(role, Mapping):
                add(role.get("name"))
        for name in (assets.get("3_sheets") or {}) if isinstance(assets.get("3_sheets"), Mapping) else {}:
            add(name)
    else:
        catalog = breakdown.get("production_assets") if isinstance(breakdown.get("production_assets"), Mapping) else {}
        for item in catalog.get(_BREAKDOWN_ASSET_KIND[kind]) or []:
            if isinstance(item, Mapping):
                add(item.get("name"))
    return names


def _apply(task: MutableMapping[str, Any], kind: str, old: str, new: str, *, impact: IdentityImpact, write: bool) -> None:
    """Walk every reference of ``old``; count it, and rewrite it to ``new`` when ``write``."""
    old = canonical_name(old)
    new = canonical_name(new)

    def hit(where: str, episode: int | None = None) -> None:
        impact.references[where] = impact.references.get(where, 0) + 1
        if episode is not None and episode not in impact.episodes:
            impact.episodes.append(episode)

    def rewrite_list(container: MutableMapping[str, Any], key: str, where: str, episode: int | None) -> None:
        values = container.get(key)
        if not isinstance(values, list):
            return
        changed = False
        result: list[Any] = []
        for value in values:
            if canonical_name(value) == old:
                hit(where, episode)
                changed = True
                if new not in result:
                    result.append(new)
                continue
            if value not in result:
                result.append(value)
        if write and changed:
            container[key] = result

    assets = task.get("assets") if isinstance(task.get("assets"), MutableMapping) else {}
    state = _state(task)
    if state is not None:
        inventory = _inventory(task, kind)
        if old in inventory:
            hit("inventory")
            if write:
                entry = inventory.pop(old)
                survivor = inventory.get(new)
                if isinstance(survivor, MutableMapping) and isinstance(entry, Mapping):
                    aliases = [alias for alias in (survivor.get("aliases") or []) if canonical_name(alias) != old]
                    survivor["aliases"] = [*aliases, old]
                    for key in ("description", "voice_style", "position"):
                        if not survivor.get(key) and entry.get(key):
                            survivor[key] = entry[key]
                else:
                    inventory[new] = entry
        if kind == "character":
            whole = state.get("inventory") if isinstance(state.get("inventory"), MutableMapping) else {}
            for edge in whole.get("relationships") or []:
                if not isinstance(edge, MutableMapping):
                    continue
                for end in ("from", "from_", "to"):
                    if canonical_name(edge.get(end)) == old:
                        hit("inventory.relationships")
                        if write:
                            edge[end] = new
        episodes = state.get("episodes") if isinstance(state.get("episodes"), MutableMapping) else {}
        for key, entry in episodes.items():
            number = int(key) if str(key).isdigit() else None
            if not isinstance(entry, MutableMapping):
                continue
            for layer in ("plan", "script"):
                block = entry.get(layer)
                if not isinstance(block, MutableMapping):
                    continue
                for scene in block.get("scenes") or []:
                    if not isinstance(scene, MutableMapping):
                        continue
                    rewrite_list(scene, _PLAN_LIST[kind], f"{layer}.{_PLAN_LIST[kind]}", number)
                    if kind == "character":
                        for utterance in scene.get("utterances") or []:
                            if isinstance(utterance, MutableMapping) and canonical_name(utterance.get("speaker")) == old and not is_narrator(old):
                                hit(f"{layer}.speaker", number)
                                if write:
                                    utterance["speaker"] = new
            prose = entry.get("prose")
            if isinstance(prose, str) and old in prose:
                hit("prose", number)
                if write:
                    entry["prose"] = prose.replace(old, new)
    breakdown = assets.get("2_breakdown") if isinstance(assets.get("2_breakdown"), MutableMapping) else None
    if breakdown is not None:
        if kind == "character":
            kept: list[Any] = []
            for role in breakdown.get("roles") or []:
                if isinstance(role, MutableMapping) and canonical_name(role.get("name")) == old:
                    hit("breakdown.roles")
                    if any(isinstance(other, Mapping) and canonical_name(other.get("name")) == new for other in kept):
                        continue
                    if write:
                        role["name"] = new
                kept.append(role)
            if write:
                breakdown["roles"] = kept
            for edge in breakdown.get("relationships") or []:
                if not isinstance(edge, MutableMapping):
                    continue
                for end in ("from", "to"):
                    if canonical_name(edge.get(end)) == old:
                        hit("breakdown.relationships")
                        if write:
                            edge[end] = new
            for scene in breakdown.get("scenes") or []:
                if isinstance(scene, MutableMapping):
                    rewrite_list(scene, "characters", "breakdown.scenes.characters", None)
        else:
            catalog = breakdown.get("production_assets")
            if isinstance(catalog, MutableMapping):
                kept = []
                for item in catalog.get(_BREAKDOWN_ASSET_KIND[kind]) or []:
                    if isinstance(item, MutableMapping) and canonical_name(item.get("name")) == old:
                        hit("breakdown.production_assets")
                        if any(isinstance(other, Mapping) and canonical_name(other.get("name")) == new for other in kept):
                            continue
                        if write:
                            item["name"] = new
                    kept.append(item)
                if write:
                    catalog[_BREAKDOWN_ASSET_KIND[kind]] = kept
    if kind == "character":
        sheets = assets.get("3_sheets")
        if isinstance(sheets, MutableMapping) and old in sheets:
            hit("sheets")
            if write:
                url = sheets.pop(old)
                sheets.setdefault(new, url)
        for item in assets.get("3_characters") or []:
            if isinstance(item, MutableMapping) and canonical_name(item.get("name")) == old:
                hit("stage3.characters")
                if write:
                    item["name"] = new
    # Shots name their cast; a clip generated for the old name is still that clip, but its prompt is not.
    stale_uids: set[int] = set()
    legacy_ids: set[str] = set()
    for shot in assets.get("4") or []:
        if not isinstance(shot, MutableMapping):
            continue
        before = dict(impact.references)
        rewrite_list(shot, "characters" if kind == "character" else _PLAN_LIST[kind], "shots", None)
        if write:
            # The storyboard's bindings name the asset too; they follow the rename without counting as a reference.
            for binding in shot.get("asset_bindings") or []:
                if isinstance(binding, MutableMapping) and binding.get("kind") == _BINDING_KIND[kind] and canonical_name(binding.get("name")) == old:
                    binding["name"] = new
        if impact.references != before:
            shot_id = shot.get("shot_id")
            if isinstance(shot_id, int) and shot_id not in impact.stale_shots:
                impact.stale_shots.append(shot_id)
            stale_uids.add(episode_cycle.shot_uid(shot))
            if shot_id not in (None, ""):
                legacy_ids.add(str(shot_id))
    if write and stale_uids:
        # Shot numbers restart at 1 in every scene: clips are matched by the shots they cover, legacy clips by number.
        for clip in assets.get("5") or []:
            if not isinstance(clip, MutableMapping) or not clip.get("video_url"):
                continue
            if clip.get("scene_id") or clip.get("shot_uids"):
                hit = not stale_uids.isdisjoint(episode_cycle.covered_uids(clip))
            else:
                hit = str(clip.get("shot_id")) in legacy_ids
            if hit:
                clip["stale"] = True
                clip["stale_reason"] = _text_of("_apply.text").format(old, new)


def preview_rename(task: Mapping[str, Any], kind: str, name: str, new_name: str) -> IdentityImpact:
    """What a rename would touch; raises when the names make no sense."""
    _check(task, kind, name, new_name, merging=False)
    impact = IdentityImpact(kind=kind, name=canonical_name(name), new_name=canonical_name(new_name))
    _apply(dict(task), kind, name, new_name, impact=impact, write=False)
    return impact


def rename_asset(task: MutableMapping[str, Any], kind: str, name: str, new_name: str) -> IdentityImpact:
    """Rename an asset everywhere it is referenced, in place."""
    _check(task, kind, name, new_name, merging=False)
    impact = IdentityImpact(kind=kind, name=canonical_name(name), new_name=canonical_name(new_name))
    _apply(task, kind, name, new_name, impact=impact, write=True)
    _record_alias(task, kind, impact.new_name, impact.name)
    impact.aliases = _aliases(task, kind, impact.new_name)
    return impact


def preview_merge(task: Mapping[str, Any], kind: str, loser: str, survivor: str) -> IdentityImpact:
    _check(task, kind, loser, survivor, merging=True)
    impact = IdentityImpact(kind=kind, name=canonical_name(loser), new_name=canonical_name(survivor))
    _apply(dict(task), kind, loser, survivor, impact=impact, write=False)
    return impact


def merge_assets(task: MutableMapping[str, Any], kind: str, loser: str, survivor: str) -> IdentityImpact:
    """Point every reference of ``loser`` at ``survivor``; the loser's name becomes an alias of the survivor."""
    _check(task, kind, loser, survivor, merging=True)
    impact = IdentityImpact(kind=kind, name=canonical_name(loser), new_name=canonical_name(survivor))
    _apply(task, kind, loser, survivor, impact=impact, write=True)
    _record_alias(task, kind, impact.new_name, impact.name)
    impact.aliases = _aliases(task, kind, impact.new_name)
    return impact


def _check(task: Mapping[str, Any], kind: str, name: str, new_name: str, *, merging: bool) -> None:
    if kind not in ASSET_KINDS:
        raise AssetIdentityError(_text_of("_check.text"))
    old, new = canonical_name(name), canonical_name(new_name)
    if not old or not new:
        raise AssetIdentityError(_text_of("_check.text.2"))
    if len(new) > 80:
        raise AssetIdentityError(_text_of("_check.text.3"))
    if old == new:
        raise AssetIdentityError(_text_of("_check.text.4"))
    names = known_names(task, kind)
    if old not in names:
        raise AssetIdentityError(_text_of("_check.text.5").format(old, _kind_label(kind)))
    if merging and new not in names:
        raise AssetIdentityError(_text_of("_check.text.6").format(new, _kind_label(kind)))
    if not merging and new in names:
        raise AssetIdentityError(_text_of("_check.text.7").format(new, _kind_label(kind)))


def _kind_label(kind: str) -> str:
    return {"character": _text_of("_kind_label.character"), "scene": _text_of("_kind_label.scene"), "prop": _text_of("_kind_label.prop")}[kind]


def _record_alias(task: MutableMapping[str, Any], kind: str, name: str, alias: str) -> None:
    """Aliases help planning recognise an asset in the source text; they are never written into references."""
    inventory = _inventory(task, kind)
    entry = inventory.get(name)
    if not isinstance(entry, MutableMapping):
        if _state(task) is None:
            return
        entry = {"description": "", "aliases": []}
        inventory[name] = entry
    aliases = [canonical_name(item) for item in (entry.get("aliases") or []) if canonical_name(item)]
    if alias not in aliases and alias != name:
        aliases.append(alias)
    entry["aliases"] = aliases


def _aliases(task: Mapping[str, Any], kind: str, name: str) -> list[str]:
    entry = _inventory(task, kind).get(name)
    return [str(item) for item in (entry.get("aliases") or [])] if isinstance(entry, Mapping) else []


__all__ = [
    "ASSET_KINDS",
    "AssetIdentityError",
    "IdentityImpact",
    "canonical_name",
    "known_names",
    "merge_assets",
    "preview_merge",
    "preview_rename",
    "rename_asset",
]
