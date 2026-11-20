# -*- coding: utf-8 -*-
"""Action and effect marks for a white-model blocking diagram.

A plain blocking diagram shows who stands where, the lenses and the walks. A fight or an effect
shot needs more to be read at a glance: who strikes whom and where the blow lands, which way the
struck figure is driven, who dodges, guards or leaves the ground, where an effect is centred and
how far it reaches, and one to three distances that matter.

Two sources, in this order:

* the motion clips a person (or the planner) put on the shot's timeline — a punch, a sword cut, a
  hit reaction, a roll, a jump. These certainly happen;
* the shot's action sentence from the storyboard, read clause by clause and narrowly, because
  that sentence is a long description of the picture (light shafts, torches, cracks, "does not
  step back"): a strike only when the same clause names the one struck (or a set piece that is
  hit); a dodge, a guard, a jump or a hit reaction only for someone a strike of this shot lands
  on; an effect only for a short list of words and only when the clause names who sends it.
  Every mark says which source it came from.

Nothing here calls a model or writes anything. Word lists, clip tables, radii and limits are data
(``app/data/prompt/action_marks.json``); an effect's radius is a placeholder size, not a measurement.
"""

from __future__ import annotations

import re
from typing import Any, Collection, Mapping, Sequence

from app.core import prompt_data
from app.core.spatial_stage import geometry as geo
from app.core.spatial_stage.models import StageActor, StageLandmark, StagePlan, StageShot

_DATA = "action_marks"
_BRIEF = "stage_brief"
_VOCABULARY = "stage_vocabulary"

Point = tuple[float, float]
Mention = tuple[int, int, str]


def _data() -> Mapping[str, Any]:
    return prompt_data.load(_DATA)


def _limit(key: str) -> float:
    return float(_data()["limits"][key])


def _ground(point: Sequence[float]) -> Point:
    return (float(point[0]), float(point[-1]))


def _rounded(point: Sequence[float]) -> list[float]:
    return [round(float(point[0]), 3), round(float(point[1]), 3)]


def mode_label(modes: Sequence[str]) -> str:
    words = _data()["modes"]
    return str(words["joiner"]).join(str(words[mode]) for mode in modes if mode != "staging") or str(words["staging"])


def effect_color_name() -> str:
    return str(_data()["effect_color"]["name"])


def effect_kinds() -> dict[str, dict[str, Any]]:
    """Kind → ``{name, radius_m, rings}``: what a person can place on the desk and what the text may name."""
    return {str(key): {"name": str(item["name"]), "radius_m": float(item["radius_m"]), "rings": int(item["rings"])}
            for key, item in _data()["effect_kinds"].items()}


def rings_for(kind: str, radius_m: float) -> int:
    """How many rings a range is drawn with: the kind's own count, fewer when the range is too small to hold them."""
    rings = int(_data()["effect_kinds"][kind]["rings"])
    return max(1, min(rings, int(float(radius_m) // float(_data()["ring_step_m"])) or 1))


# --------------------------------------------------------------------------- reading the sentence


def _mentions(clause: str, names: Sequence[str]) -> list[Mention]:
    """Every name in the clause as ``(start, end, name)``, longest names first so a name inside a longer one is not read twice."""
    taken: list[Mention] = []
    for name in sorted(names, key=len, reverse=True):
        start = clause.find(name)
        while start >= 0:
            end = start + len(name)
            if not any(start < other_end and other_start < end for other_start, other_end, _name in taken):
                taken.append((start, end, name))
            start = clause.find(name, end)
    return sorted(taken)


def _before(found: Sequence[Mention], index: int) -> str:
    """The name that ends nearest before ``index``."""
    return next((name for _start, end, name in reversed(found) if end <= index), "")


def _after(found: Sequence[Mention], index: int, *, other_than: str = "") -> str:
    return next((name for start, _end, name in found if start >= index and name != other_than), "")


def _clauses(text: str) -> list[str]:
    stops = str(prompt_data.load(_VOCABULARY)["blocking_verbs"]["clause_stops"])
    return [part for part in re.split("[" + re.escape(stops) + "]", text or "") if part.strip()]


# --------------------------------------------------------------------------- one strike


def _strike(
    attacker: StageActor, target: StageActor | None, kind: str, color: str, *, shot_id: int, at_s: float | None, source: str,
) -> dict[str, Any]:
    words = _data()["strike_kinds"][kind]
    here = _ground(attacker.position)
    if target is None:
        heading = geo.forward_of(attacker.yaw_deg)
        start = geo.add(here, geo.scale(heading, _limit("hand_m")))
        tip = geo.add(here, geo.scale(heading, _limit("hand_m") + _limit("open_strike_m")))
        metres = _limit("open_strike_m")
    else:
        there = _ground(target.position)
        metres = geo.distance(here, there)
        heading = geo.unit(geo.sub(there, here), geo.forward_of(attacker.yaw_deg))
        if metres <= _limit("hand_m") + _limit("body_m") + 0.05:
            start, tip = here, geo.midpoint(here, there)
        else:
            start = geo.add(here, geo.scale(heading, _limit("hand_m")))
            tip = geo.sub(there, geo.scale(heading, _limit("body_m")))
    return {
        "attacker": attacker.name, "target": target.name if target else "", "kind": kind,
        "short": str(words["short"]), "label": str(words["label"]), "color": color,
        "from": _rounded(start), "to": _rounded(tip), "heading": [round(heading[0], 4), round(heading[1], 4)],
        "meters": round(metres, 1), "shot_id": shot_id, "at_s": at_s, "source": source,
        "source_label": str(_data()["sources"][source]), "force_to": None, "reaction": "",
    }


def _in_front(attacker: StageActor, others: Sequence[StageActor]) -> StageActor | None:
    """Whoever the attacker faces within reach: the nearest figure inside the strike cone."""
    here = _ground(attacker.position)
    best: tuple[float, StageActor] | None = None
    for other in others:
        if other.name == attacker.name:
            continue
        there = _ground(other.position)
        metres = geo.distance(here, there)
        if metres < 0.05 or metres > _limit("strike_reach_m"):
            continue
        off = abs(geo.normalize_yaw(geo.yaw_toward(here, there) - attacker.yaw_deg))
        if off <= _limit("strike_cone_deg") and (best is None or metres < best[0]):
            best = (metres, other)
    return best[1] if best else None


# --------------------------------------------------------------------------- the marks of one diagram


class _Marks:
    def __init__(self, plan: StagePlan, staged: Sequence[StageActor], colors: Mapping[str, Mapping[str, str]], pieces: Sequence[StageLandmark]):
        self.plan = plan
        self.named = [actor for actor in staged if not actor.crowd_id and actor.role != "crowd"]
        self.by_name = {actor.name: actor for actor in self.named}
        self.colors = colors
        self.pieces = {piece.name: piece for piece in pieces if piece.name}
        self.strikes: list[dict[str, Any]] = []
        self.effects: list[dict[str, Any]] = []
        self.acts: dict[str, list[str]] = {}
        self.reactions: dict[str, str] = {}
        self.nodes: list[dict[str, Any]] = []

    # -- collecting

    def act(self, name: str, kind: str) -> None:
        if name in self.by_name and kind not in self.acts.setdefault(name, []):
            self.acts[name].append(kind)

    def react(self, name: str, kind: str) -> None:
        if name not in self.by_name:
            return
        rank = list(_data()["reaction_rank"])
        held = self.reactions.get(name)
        if held is None or rank.index(kind) < rank.index(held):
            self.reactions[name] = kind
        self.act(name, self.reactions[name])

    def strike(self, attacker: str, target: str, kind: str, *, shot_id: int, at_s: float | None, source: str) -> bool:
        """Add the strike unless it is already drawn; a sentence about a blow a clip already shows adds nothing."""
        if attacker not in self.by_name or attacker == target or (target and target not in self.by_name):
            return False
        if any(item["attacker"] == attacker and item["target"] == target and item["shot_id"] == shot_id
               and (item["kind"] == kind or source == "text") for item in self.strikes):
            return False
        self.strikes.append(_strike(
            self.by_name[attacker], self.by_name.get(target), kind, str(self.colors[attacker]["hex"]),
            shot_id=shot_id, at_s=at_s, source=source,
        ))
        return True

    def effect(
        self, kind: str, centre: Point, *, source: str, origin: Point | None, shot_id: int,
        radius: float | None = None, read_from: str = "text", note: str = "", marker_id: str = "",
    ) -> None:
        table = _data()["effect_kinds"][kind]
        if any(item["kind"] == kind and geo.distance(tuple(item["center"]), centre) < 0.5 for item in self.effects):
            return
        reach = float(table["radius_m"]) if radius is None else float(radius)
        flow = origin if origin is not None and geo.distance(origin, centre) >= _limit("flow_min_m") else None
        inside = [actor.name for actor in self.named
                  if actor.name != source and geo.distance(_ground(actor.position), centre) <= reach]
        self.effects.append({
            "kind": str(kind), "name": note or str(table["name"]), "center": _rounded(centre), "radius_m": round(reach, 2),
            "rings": rings_for(kind, reach), "from": _rounded(flow) if flow else None, "source": source, "inside": inside,
            "shot_id": shot_id, "color": str(_data()["effect_color"]["hex"]), "read_from": read_from,
            "source_label": str(_data()["sources"][read_from]), "marker_id": marker_id,
        })

    # -- the markers a person placed on the desk

    def read_markers(self, shots: Sequence[StageShot]) -> None:
        shot_ids = [shot.shot_id for shot in shots]
        for marker in self.plan.effects:
            on = next((shot_id for shot_id in shot_ids if marker.applies_to(shot_id)), None)
            if on is None or marker.kind not in _data()["effect_kinds"]:
                continue
            sender = self.by_name.get(marker.source)
            self.effect(
                marker.kind, _ground(marker.position), source=sender.name if sender else "",
                origin=_ground(sender.position) if sender else None, shot_id=on, radius=marker.radius_m,
                read_from="manual", note=marker.note, marker_id=marker.id,
            )

    # -- the timeline's motion clips

    def read_clips(self, shot: StageShot) -> None:
        timeline = self.plan.timelines.get(str(shot.shot_id))
        if timeline is None:
            return
        tables = _data()["clips"]
        names = prompt_data.load(_BRIEF)["clip_names"]
        rows: list[tuple[float, str, Any]] = [
            (clip.start, name, clip) for name, clips in timeline.clips.items() if name in self.by_name for clip in clips
        ]
        for start, name, clip in sorted(rows, key=lambda row: (row[0], row[1])):
            kind = ""
            if clip.clip in tables["strike"]:
                kind = "strike"
                target = _in_front(self.by_name[name], self.named)
                self.strike(name, target.name if target else "", str(tables["strike"][clip.clip]),
                            shot_id=shot.shot_id, at_s=round(start, 2), source="clip")
            elif clip.clip in tables["react"]:
                kind = str(tables["react"][clip.clip])
                self.react(name, kind)
            else:
                kind = next((key for key in ("evade", "guard", "air") if clip.clip in tables[key]), "")
                if kind:
                    self.act(name, kind)
            if kind:
                self.nodes.append({
                    "shot_id": shot.shot_id, "at_s": round(start, 2), "end_s": round(clip.end, 2), "name": name,
                    "what": str(names.get(clip.clip, clip.clip)), "source": "clip",
                })

    # -- the storyboard's action sentence

    def read_text(self, shot: StageShot) -> None:
        words = _data()["text"]
        passive = re.compile(str(words["passive"]))
        names = list(self.by_name)
        subject = ""
        # What the text says a figure does; kept only for whoever a strike of this shot lands on.
        said: list[tuple[str, str]] = []
        for clause in _clauses(shot.action):
            found = _mentions(clause, names)
            set_pieces = _mentions(clause, list(self.pieces))
            struck = ""
            for pattern, kind in words["strike"]:
                match = re.search(str(pattern), clause)
                if match is None:
                    continue
                attacker = _before(found, match.start()) or subject
                said_from = max([end for _start, end, name in found if name == attacker and end <= match.start()] or [0])
                if any(re.search(str(entry[0]), clause[said_from:match.start()]) for entry in _data()["effects"]):
                    # The thing that flies at them is an effect, not the attacker's body.
                    continue
                target = _after(found, match.end(), other_than=attacker)
                told = passive.search(clause[:match.start()])
                victim = _before(found, told.start()) if told else ""
                if victim:
                    doer = next((name for start, end, name in found if start >= told.end() and end <= match.start()), "")
                    attacker, target = doer or (subject if subject != victim else ""), victim
                if target:
                    struck = target
                    if attacker and self.strike(attacker, target, str(kind), shot_id=shot.shot_id, at_s=None, source="text"):
                        self.nodes.append({"shot_id": shot.shot_id, "at_s": None, "end_s": None, "name": attacker,
                                           "what": clause.strip()[:40], "source": "text"})
                elif attacker in self.by_name:
                    piece = _after(set_pieces, match.end())
                    if piece:
                        self.effect(
                            str(_data()["impact_kind"]), _ground(self.pieces[piece].position), source=attacker,
                            origin=_ground(self.by_name[attacker].position), shot_id=shot.shot_id,
                        )
            for pattern, kind in words["react"]:
                match = re.search(str(pattern), clause)
                if match is not None:
                    said.append((struck or _before(found, match.start()) or subject, str(kind)))
                    break
            for key in ("evade", "guard", "air"):
                match = re.search(str(words[key]), clause)
                if match is not None:
                    said.append((_before(found, match.start()) or subject, key))
            for entry in _data()["effects"]:
                match = re.search(str(entry[0]), clause)
                if match is None:
                    continue
                source = _before(found, match.start())
                caster = self.by_name.get(source)
                if caster is None:
                    continue
                origin = _ground(caster.position)
                piece = (_after(set_pieces, match.end()) or (set_pieces[0][2] if set_pieces else ""))
                aimed = _after(found, match.end(), other_than=source)
                if piece:
                    centre = _ground(self.pieces[piece].position)
                elif aimed:
                    centre = _ground(self.by_name[aimed].position)
                else:
                    centre = geo.add(origin, geo.scale(geo.forward_of(caster.yaw_deg), _limit("cast_m")))
                self.effect(str(entry[1]), centre, source=source, origin=origin, shot_id=shot.shot_id)
            if found:
                subject = found[0][2]
        struck_here = {item["target"] for item in self.strikes if item["shot_id"] == shot.shot_id and item["target"]}
        rank = set(_data()["reaction_rank"])
        for name, kind in said:
            if name in struck_here:
                (self.react if kind in rank else self.act)(name, kind)

    # -- what the picture needs

    def finish(self, moving: Collection[str]) -> dict[str, Any]:
        data = _data()
        strikes = self.strikes[: int(_limit("max_strikes"))]
        for item in strikes:
            reaction = self.reactions.get(item["target"])
            if not reaction:
                continue
            item["reaction"] = str(data["reactions"][reaction])
            if item["target"] not in moving:
                tip = geo.add(tuple(item["to"]), geo.scale(tuple(item["heading"]), _limit("force_m")))
                item["force_to"] = _rounded(tip)
        effects = self.effects[: int(_limit("max_effects"))]
        for number, item in enumerate(effects, start=1):
            item["id"] = str(data["effect_id"]).format(number)

        route_kinds: dict[str, dict[str, str]] = {}
        for name in moving:
            kind = self.reactions.get(name) or next((key for key in ("evade", "air") if key in self.acts.get(name, [])), "")
            if kind:
                route_kinds[name] = {"kind": kind, "label": str(data["route_labels"][kind])}

        cap = int(_limit("max_badges"))
        acts = {name: [str(data["badges"][kind]) for kind in kinds[:cap]] for name, kinds in self.acts.items() if kinds}

        modes = ["staging"]
        if strikes or acts or any(actor.posture == "fight" for actor in self.named):
            modes.append("action")
        if effects:
            modes.append("vfx")
        return {
            "modes": modes, "mode_label": mode_label(modes), "strikes": strikes, "effects": effects, "acts": acts,
            "route_kinds": route_kinds, "distances": self._distances(strikes), "nodes": self.nodes[: int(_limit("max_nodes"))],
        }

    def _distances(self, strikes: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        # A strike line already carries its own metres; a ruler is for a picture without one.
        pairs: list[tuple[str, str]] = []
        if not any(item["target"] for item in strikes) and len(self.named) >= 2:
            leads = [actor for actor in self.named if actor.role == "principal"]
            pool = leads if len(leads) >= 2 else self.named
            first, second = min(
                ((a, b) for index, a in enumerate(pool) for b in pool[index + 1:]),
                key=lambda pair: geo.distance(_ground(pair[0].position), _ground(pair[1].position)),
            )
            pairs.append((first.name, second.name))
        rows: list[dict[str, Any]] = []
        for first, second in pairs[: int(_limit("max_distances"))]:
            a, b = _ground(self.by_name[first].position), _ground(self.by_name[second].position)
            metres = geo.distance(a, b)
            if metres >= 0.3:
                rows.append({"a": first, "b": second, "meters": round(metres, 1), "from": _rounded(a), "to": _rounded(b)})
        return rows


def read(
    plan: StagePlan, shots: Sequence[StageShot], staged: Sequence[StageActor],
    colors: Mapping[str, Mapping[str, str]], pieces: Sequence[StageLandmark], moving: Collection[str] = (),
) -> dict[str, Any]:
    """The marks of one diagram: ``staged`` is the cast as the diagram draws it, ``moving`` who walks in it."""
    marks = _Marks(plan, staged, colors, pieces)
    # A person's own markers first: they take the first numbers, and the text does not repeat them.
    marks.read_markers(shots)
    for shot in shots:
        marks.read_clips(shot)
        marks.read_text(shot)
    return marks.finish(moving)


__all__ = ["effect_color_name", "effect_kinds", "mode_label", "read", "rings_for"]
