# -*- coding: utf-8 -*-
"""Name cards: the first time a person comes on screen, their name and identity stand beside them in vertical
text; after that they never show again.

Nothing here calls a model. Who is in a shot and on which side of the frame comes from the storyboard
(``characters`` and ``spatial.screen``); the identity is the opening piece of the character's record. The cards are
kept on the edit timeline's clips (``name_cards``) so the editor can change them, and the compositor burns them in.

"First time" is counted over the cut as it stands: a person whose first clip was rejected gets the card on the next
clip they are in. In a series the people already seen in earlier episodes are not introduced again (``scope``).
Wording, timing, sizes and limits live in app/data/prompt/character_intro.json.
"""

from __future__ import annotations

import re
from copy import deepcopy
from typing import Any, Mapping, Sequence

from app.core import episode_cycle, prompt_data

_FILE = "character_intro"
KEY = "name_cards"
EDITED = "name_cards_edited"
SIDES = ("left", "right")


class NameCardError(ValueError):
    pass


def _table(key: str) -> Any:
    return prompt_data.value(_FILE, key)


def _assets(task: Mapping[str, Any]) -> Mapping[str, Any]:
    assets = task.get("assets") if isinstance(task, Mapping) else None
    return assets if isinstance(assets, Mapping) else {}


def scope_of(task: Mapping[str, Any]) -> str:
    config = task.get("config") if isinstance(task.get("config"), Mapping) else {}
    chosen = str(config.get("name_card_scope") or "")
    return chosen if chosen in _table("scopes") else str(_table("scope"))


def identity_from(description: Any) -> str:
    """The identity a character record opens with: the first piece before a separator, or nothing when it runs long."""
    rule = _table("identity")
    text = str(description or "").strip()
    piece = re.split(str(rule["split"]), text, maxsplit=1)[0].strip() if text else ""
    return piece if 0 < len(piece) <= int(rule["max_chars"]) else ""


def identities(task: Mapping[str, Any]) -> dict[str, str]:
    """name → identity for every character the project has a record of (the identity may be empty)."""
    assets = _assets(task)
    found: dict[str, str] = {}
    inventory = (assets.get("2_screenwriting") or {}).get("inventory") if isinstance(assets.get("2_screenwriting"), Mapping) else None
    listed = inventory.get("characters") if isinstance(inventory, Mapping) else None
    for group in listed if isinstance(listed, list) else [listed]:
        if isinstance(group, Mapping):
            for name, record in group.items():
                description = record.get("description") if isinstance(record, Mapping) else record
                found[str(name)] = identity_from(description)
    for record in assets.get("3_characters") or []:
        if isinstance(record, Mapping) and record.get("name"):
            name = str(record["name"])
            found[name] = identity_from(record.get("desc") or record.get("description")) or found.get(name, "")
    from app.core import submission_pack  # 投稿材料里写过的身份是人看过的，以它为准
    pack = submission_pack.stored(task)
    details = pack.get("details") if isinstance(pack, Mapping) and isinstance(pack.get("details"), Mapping) else {}
    limit = int(_table("identity")["max_chars"])
    for person in details.get("characters") or []:
        if isinstance(person, Mapping) and str(person.get("name") or "") in found:
            written = str(person.get("identity") or "").strip()
            if 0 < len(written) <= limit:
                found[str(person["name"])] = written
    return found


def _side_of(region: Any) -> str | None:
    text = str(region or "")
    words = _table("sides")
    hits = {side for side in SIDES if any(word in text for word in words[side])}
    return next(iter(hits)) if len(hits) == 1 else None


def _shots_by_uid(task: Mapping[str, Any]) -> dict[int, Mapping[str, Any]]:
    return {episode_cycle.shot_uid(shot): shot for shot in _assets(task).get("4") or [] if isinstance(shot, Mapping)}


def _beats(clip: Mapping[str, Any], shots: Mapping[int, Mapping[str, Any]]) -> list[tuple[float, Mapping[str, Any]]]:
    """(seconds into the clip, the shot) for every storyboard moment the clip films, in order."""
    slice_info = clip.get("slice") if isinstance(clip.get("slice"), Mapping) else {}
    beats = [beat for beat in slice_info.get("beats") or [] if isinstance(beat, Mapping)]
    if not beats:
        uid = episode_cycle.shot_uid(clip)
        return [(0.0, shots.get(uid, clip))]
    out, at = [], 0.0
    for beat in beats:
        uid = episode_cycle.shot_uid({**beat, "scene_id": beat.get("scene_id") or clip.get("scene_id")})
        shot = shots.get(uid) or beat
        out.append((at, {**shot, "characters": shot.get("characters") or beat.get("characters") or []}))
        try:
            at += max(0.0, float(beat.get("seconds") or 0))
        except (TypeError, ValueError):
            pass
    return out


def _seen_earlier(task: Mapping[str, Any], episode: int | None, known: Mapping[str, str]) -> set[str]:
    """The people already on screen in earlier episodes: a series introduces each of them once."""
    if episode is None or scope_of(task) != "drama":
        return set()
    return {
        str(name) for shot in _assets(task).get("4") or [] if isinstance(shot, Mapping) and episode_cycle.episode_of(shot) < episode
        for name in shot.get("characters") or [] if str(name) in known
    }


def _standing(name: str, cast: Sequence[str], regions: Mapping[str, Any]) -> tuple[str | None, int]:
    """Where a newcomer's card goes in one storyboard moment, and how many others it could be mistaken for (0 = clear).

    Alone in the shot: the card takes the free side, away from them. With others (extras the storyboard placed
    count too): it stays on their own side, and is clear only when nobody else stands there; a card beside two
    people names the wrong one half the time.
    """
    other = {"left": "right", "right": "left"}
    side = _side_of(regions.get(name))
    company = [person for person in dict.fromkeys([*cast, *regions]) if person != name]
    if not company:
        return (other[side] if side else None), 0
    if side is None:
        return None, len(company)
    return side, sum(1 for person in company if _side_of(regions.get(person)) == side)


def _placed(names: Sequence[tuple[str, str | None, bool]], at: float, known: Mapping[str, str]) -> list[dict[str, Any]]:
    """Cards for the people introduced in one storyboard moment: each on their side, at most a few abreast."""
    timing = _table("timing")
    per_side = max(1, int(_table("columns_per_side")))
    default = str(_table("default_side"))
    other = {"left": "right", "right": "left"}
    start = at + float(timing["lead"])
    used: dict[str, int] = {"left": 0, "right": 0}
    cards, unknown = [], 0
    for name, side, unsure in names:
        if side is None:
            # 分镜没写他站哪一侧：先放默认的那一侧，再有就左右交替。
            side = default if unknown % 2 == 0 else other[default]
            unknown += 1
        if used[side] >= per_side and used[other[side]] < per_side:
            side = other[side]
        if used[side] >= per_side:
            start += float(timing["seconds"]) + float(timing["gap"])
            used = {"left": 0, "right": 0}
        card = {"name": name, "identity": known.get(name, ""), "side": side, "slot": used[side], "at": round(start, 2)}
        if unsure:
            # 分镜里他这一侧还站着别人：位置是猜的，剪辑台上标出来请人看一眼。
            card["unsure"] = True
        cards.append(card)
        used[side] += 1
    return cards


def due(task: Mapping[str, Any], timeline: Mapping[str, Any]) -> dict[int, list[dict[str, Any]]]:
    """clip position → the cards that fall on it.

    Each person gets one card, in the first moment of the cut where it can only be read as theirs (see
    ``_standing``), as long as that comes within a few clips of their entrance (``defer_clips``). Otherwise the
    card goes where they first come on, marked ``unsure`` so the editor is asked to look.
    """
    known = identities(task)
    if not known:
        return {}
    limit = int(_table("identity")["name_max_chars"])
    shots = _shots_by_uid(task)
    footage = {episode_cycle.shot_uid(clip): clip for clip in _assets(task).get("5") or [] if isinstance(clip, Mapping)}
    episode = timeline.get("episode") if isinstance(timeline.get("episode"), int) else None
    seen = _seen_earlier(task, episode, known)
    # 剪辑里的每个分镜瞬间：(片段位置, 片段内第几秒, 这一刻在场的人, 各人的画面区域)。
    moments: list[tuple[int, float, list[str], dict[str, Any]]] = []
    for position, clip in enumerate(timeline.get("clips") or []):
        if not isinstance(clip, Mapping) or (clip.get("review") or {}).get("decision") == "rejected" or not clip.get("video_url"):
            continue
        for at, shot in _beats(footage.get(clip.get("shot_uid")) or clip, shots):
            screen = (shot.get("spatial") or {}).get("screen") if isinstance(shot.get("spatial"), Mapping) else None
            regions = {str(entry.get("name")): entry.get("region") for entry in screen or [] if isinstance(entry, Mapping)}
            moments.append((position, at, [str(name) for name in shot.get("characters") or []], regions))
    cut_order = {position: order for order, position in enumerate(dict.fromkeys(position for position, *_ in moments))}
    wait = int(_table("defer_clips"))
    chosen: dict[int, list[tuple[str, str | None, bool]]] = {}
    for name in dict.fromkeys(person for _, _, cast, _ in moments for person in cast):
        if name not in known or name in seen or len(name) > limit:
            continue
        there = [(index, _standing(name, cast, regions)) for index, (_, _, cast, regions) in enumerate(moments) if name in cast]
        first_clip = moments[there[0][0]][0]
        soon = [entry for entry in there if cut_order[moments[entry[0]][0]] - cut_order[first_clip] <= wait]
        index, (side, rivals) = next((entry for entry in soon if entry[1][1] == 0), there[0])
        chosen.setdefault(index, []).append((name, side, rivals > 0))
    out: dict[int, list[dict[str, Any]]] = {}
    for index in sorted(chosen):
        position, at = moments[index][0], moments[index][1]
        out.setdefault(position, []).extend(_placed(chosen[index], at, known))
    most = int(_table("limits")["cards_per_clip"])
    return {position: cards[:most] for position, cards in out.items()}


def with_cards(timeline: Mapping[str, Any], task: Mapping[str, Any]) -> Mapping[str, Any]:
    """The timeline with every clip's name cards up to date; clips the editor wrote by hand keep what was written.

    Returns the very same object when nothing changes, so reading a timeline does not look like an edit.
    """
    planned = due(task, timeline)
    clips = timeline.get("clips") or []
    wanted = [
        deepcopy(clip.get(KEY) or []) if isinstance(clip, Mapping) and clip.get(EDITED) else planned.get(position, [])
        for position, clip in enumerate(clips)
    ]
    if all(isinstance(clip, Mapping) and (clip.get(KEY) or []) == cards for clip, cards in zip(clips, wanted)):
        return timeline
    new = deepcopy(dict(timeline))
    for clip, cards in zip(new.get("clips") or [], wanted):
        if isinstance(clip, dict):
            clip[KEY] = cards
    return new


def cleaned(cards: Any) -> list[dict[str, Any]]:
    """Cards an editor wrote, checked and tidied."""
    errors, limits, rule = _table("errors"), _table("limits"), _table("identity")
    if not isinstance(cards, list) or any(not isinstance(card, Mapping) for card in cards):
        raise NameCardError(str(errors["cards"]))
    if len(cards) > int(limits["cards_per_clip"]):
        raise NameCardError(str(errors["too_many"]).format(limit=limits["cards_per_clip"]))
    out: list[dict[str, Any]] = []
    used: dict[str, int] = {"left": 0, "right": 0}
    for index, card in enumerate(cards, start=1):
        name = re.sub(r"\s+", "", str(card.get("name") or ""))[: int(rule["name_max_chars"])]
        if not name:
            raise NameCardError(str(errors["name"]).format(index=index))
        side = str(card.get("side") or _table("default_side"))
        if side not in SIDES:
            raise NameCardError(str(errors["side"]).format(index=index))
        try:
            at = max(0.0, float(card.get("at") if card.get("at") is not None else _table("timing")["lead"]))
        except (TypeError, ValueError):
            at = float(_table("timing")["lead"])
        identity = re.sub(r"\s+", "", str(card.get("identity") or ""))[: int(limits["note_chars"])]
        out.append({"name": name, "identity": identity, "side": side, "slot": used[side], "at": round(at, 2)})
        used[side] += 1
    return out


def unsure(timeline: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The cards whose place was a guess, for the editor to look at: [{shot_uid, scene_id, name}]."""
    return [
        {"shot_uid": clip.get("shot_uid"), "scene_id": clip.get("scene_id"), "name": card.get("name")}
        for clip in timeline.get("clips") or [] if isinstance(clip, Mapping)
        for card in clip.get(KEY) or [] if isinstance(card, Mapping) and card.get("unsure")
    ]


def window(card: Mapping[str, Any], *, trim_start: float, kept: float) -> tuple[float, float] | None:
    """When a card shows inside the trimmed clip: (start, end) seconds, or None when the clip is too short to read it.

    A card whose moment was trimmed away moves to the start of what is left; one that would run past the end
    moves earlier. It is never dropped for timing alone, because this is the only time the person is named.
    """
    timing = _table("timing")
    seconds, least = float(timing["seconds"]), float(timing["min_seconds"])
    if kept < least:
        return None
    length = min(seconds, kept)
    start = max(0.0, float(card.get("at") or 0.0) - max(0.0, trim_start))
    start = max(0.0, min(start, kept - length))
    return round(start, 3), round(start + length, 3)


def for_plan(clip: Mapping[str, Any]) -> list[dict[str, Any]]:
    """What the compositor draws for one clip."""
    return [
        {"name": str(card.get("name") or ""), "identity": str(card.get("identity") or ""),
         "side": card.get("side") if card.get("side") in SIDES else str(_table("default_side")),
         "slot": int(card.get("slot") or 0), "at": float(card.get("at") or 0.0)}
        for card in clip.get(KEY) or [] if isinstance(card, Mapping) and card.get("name")
    ]


__all__ = ["EDITED", "KEY", "NameCardError", "SIDES", "cleaned", "due", "for_plan", "identities", "identity_from", "scope_of", "unsure", "window", "with_cards"]
