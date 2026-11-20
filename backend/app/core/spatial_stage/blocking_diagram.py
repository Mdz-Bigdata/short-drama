# -*- coding: utf-8 -*-
"""A staged scene as a series of white-model blocking diagrams.

One diagram per staging beat: consecutive shots that leave everyone where they stand share a
diagram and show every lens that films them (CAM 1, CAM 2 …); a shot in which somebody walks, or
in which the lens travels, gets a diagram of its own with the route drawn on it. Each diagram
carries what the desk needs to draw it (figures with one distinct colour each, set pieces, lenses
with their real horizontal field of view, routes with their order) and a text prompt that asks an
image model for the same picture.

Everything is read from the plan: no model is called and nothing is written. Wording, the palette
and the limits are data (``app/data/prompt/blocking_diagram.json``).
"""

from __future__ import annotations

import colorsys
import math
from typing import Any, Mapping, Sequence

from app.core import prompt_data
from app.core.spatial_stage import action_marks
from app.core.spatial_stage import geometry as geo
from app.core.spatial_stage import wording
from app.core.spatial_stage.models import StageActor, StageCamera, StageLandmark, StagePlan, StageShot

_DATA = "blocking_diagram"


class BlockingDiagramError(ValueError):
    """A request the diagram cannot honour: an unknown view, a scene without shots."""


def _data() -> Mapping[str, Any]:
    return prompt_data.load(_DATA)


def _line(key: str, /, **values: object) -> str:
    return str(_data()["lines"][key]).format(**values)


def _limit(key: str) -> float:
    return float(_data()["limits"][key])


def views() -> dict[str, dict[str, Any]]:
    """View id → ``{label, tilt_deg}``; the tilt is how far above the ground the viewer looks from."""
    return {key: {"label": str(item["label"]), "tilt_deg": float(item["tilt_deg"])} for key, item in _data()["views"].items()}


def default_view() -> str:
    return str(_data()["default_view"])


# --------------------------------------------------------------------------- colours


def _hue(hex_color: str) -> float | None:
    """Hue in degrees, or ``None`` for a colour too grey to be told apart by hue."""
    text = hex_color.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    try:
        red, green, blue = (int(text[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return None
    hue, _lightness, saturation = colorsys.rgb_to_hls(red, green, blue)
    return None if saturation < 0.25 else hue * 360


def _hue_gap(a: float, b: float) -> float:
    gap = abs(a - b) % 360
    return min(gap, 360 - gap)


def _hue_name(hex_color: str) -> str:
    hue = _hue(hex_color)
    if hue is None:
        return str(_data()["extra_color"]["name"])
    for ceiling, name in _data()["hue_names"]:
        if hue < float(ceiling):
            return str(name)
    return str(_data()["hue_names"][-1][1])


def assign_colors(actors: Sequence[StageActor]) -> dict[str, dict[str, str]]:
    """Name → ``{hex, name}``: one colour per named character, far enough apart in hue to tell at a glance.

    A colour set by hand on the desk is kept when it is not grey and not close to one already
    taken; everyone else gets the palette colour furthest from those in use. Crowd members share
    the neutral grey.
    """
    palette = [{"hex": str(item["hex"]), "name": str(item["name"])} for item in _data()["palette"]]
    extra = {"hex": str(_data()["extra_color"]["hex"]), "name": str(_data()["extra_color"]["name"])}
    gap = float(_data()["min_hue_gap_deg"])
    named = [actor for actor in actors if not actor.crowd_id and actor.role != "crowd"]
    named.sort(key=lambda actor: 0 if actor.role == "principal" else 1)
    taken: list[float] = []
    chosen: dict[str, dict[str, str]] = {}
    pending: list[StageActor] = []
    for actor in named:
        hue = _hue(actor.color) if actor.color else None
        if hue is not None and all(_hue_gap(hue, other) >= gap for other in taken):
            chosen[actor.name] = {"hex": actor.color.upper(), "name": _hue_name(actor.color)}
            taken.append(hue)
        else:
            pending.append(actor)
    free = list(palette)
    for actor in pending:
        if not free:
            free = list(palette)
        pick = max(free, key=lambda item: min([_hue_gap(_hue(item["hex"]) or 0.0, other) for other in taken] or [360.0]))
        free.remove(pick)
        chosen[actor.name] = pick
        taken.append(_hue(pick["hex"]) or 0.0)
    for actor in actors:
        chosen.setdefault(actor.name, extra)
    return chosen


# --------------------------------------------------------------------------- staging beats


def _ground(point: Sequence[float]) -> tuple[float, float]:
    """The ground point under a 2D mark or a 3D position."""
    return (float(point[0]), float(point[-1]))


def _same_place(a: Sequence[float], b: Sequence[float]) -> bool:
    return geo.distance(_ground(a), _ground(b)) <= _limit("same_place_m")


def _route(plan: StagePlan, shot: StageShot, first: StageActor, last: StageActor) -> list[tuple[float, float]]:
    """Where ``first`` walks during ``shot``; empty when they stay put."""
    timeline = plan.timelines.get(str(shot.shot_id))
    track = timeline.actors.get(first.name) if timeline is not None else None
    points: list[tuple[float, float]] = []
    if track:
        for key in track:
            if key.position is not None and (not points or not _same_place(points[-1], key.position)):
                points.append(_ground(key.position))
        if points and not _same_place(points[0], first.position) and track[0].time > 1e-6:
            points.insert(0, _ground(first.position))
    else:
        points = [_ground(first.position), _ground(last.position)]
    if len(points) < 2 or geo.distance(points[0], points[-1]) <= _limit("same_place_m") and len(points) == 2:
        return []
    cap = int(_limit("path_points"))
    if len(points) > cap:
        step = (len(points) - 1) / (cap - 1)
        points = [points[round(index * step)] for index in range(cap)]
    return points


def _first_move_time(plan: StagePlan, shot: StageShot, name: str) -> float:
    timeline = plan.timelines.get(str(shot.shot_id))
    track = timeline.actors.get(name) if timeline is not None else None
    if not track:
        return 0.0
    seen: tuple[float, float] | None = None
    for key in track:
        if key.position is None:
            continue
        if seen is not None and not _same_place(seen, key.position):
            return float(key.time)
        seen = _ground(key.position)
    return 0.0


def _staging(plan: StagePlan, shot: StageShot) -> tuple:
    """What a still picture of the shot shows: who is on, where, facing where, in what posture."""
    return tuple(
        (actor.name, round(actor.position[0], 2), round(actor.position[1], 2), round(geo.normalize_yaw(actor.yaw_deg)), actor.posture)
        for actor in plan.actors_in(shot)
    )


def _camera_travels(camera: StageCamera | None) -> bool:
    return bool(camera and camera.move.kind != "static" and camera.move.end_position is not None
                and not _same_place(camera.position, camera.move.end_position))


def _beats(plan: StagePlan) -> list[list[StageShot]]:
    """Consecutive shots that share one still staging, with a moving shot always on its own."""
    cameras = {camera.id: camera for camera in plan.cameras}
    beats: list[list[StageShot]] = []
    previous: tuple | None = None
    for shot in plan.shots:
        starts = {actor.name: actor for actor in plan.actors_in(shot)}
        ends = {actor.name: actor for actor in plan.actors_in(shot, at_end=True)}
        moving = any(_route(plan, shot, actor, ends.get(name, actor)) for name, actor in starts.items())
        staging = _staging(plan, shot)
        if moving or _camera_travels(cameras.get(shot.camera_id)) or previous is None or staging != previous:
            beats.append([shot])
        else:
            beats[-1].append(shot)
        # A shot with movement ends somewhere else: the next still shot starts a new beat.
        previous = None if moving else staging
    return beats


# --------------------------------------------------------------------------- wording


def _metres(value: float) -> str:
    rounded = round(float(value) * 2) / 2
    return f"{rounded:g}" if rounded >= 0.5 else "0.5"


def _place(point: Sequence[float], centre: tuple[float, float]) -> str:
    """Where a ground point is, from the middle of the floor: 偏左 2 米、靠深处 1.5 米."""
    words = _data()["place"]
    dx, dz = point[0] - centre[0], point[1] - centre[1]
    parts: list[str] = []
    if abs(dx) >= 0.25:
        parts.append(str(words["x_right" if dx > 0 else "x_left"]).format(m=_metres(abs(dx))))
    if abs(dz) >= 0.25:
        parts.append(str(words["z_near" if dz > 0 else "z_far"]).format(m=_metres(abs(dz))))
    if not parts:
        return str(words["center"])
    return parts[0] if len(parts) == 1 else str(words["joined"]).format(x=parts[0], z=parts[1])


def _facing(actor: StageActor, others: Sequence[StageActor]) -> str:
    words = _data()["facing"]
    tolerance = _limit("facing_tolerance_deg")
    here = _ground(actor.position)
    near = sorted((other for other in others if other.name != actor.name and not other.crowd_id),
                  key=lambda other: geo.distance(here, _ground(other.position)))
    for other in near:
        there = _ground(other.position)
        if geo.distance(here, there) < 0.2:
            continue
        off = abs(geo.normalize_yaw(geo.yaw_toward(here, there) - actor.yaw_deg))
        if off <= tolerance:
            return str(words["toward"]).format(name=other.name)
    yaw = geo.normalize_yaw(actor.yaw_deg)
    # yaw 0 faces +Z, the near edge of the picture; +90 faces +X, the right edge.
    sector = round(yaw / 45) % 8
    key = ("near", "near_right", "right", "far_right", "far", "far_left", "left", "near_left")[sector]
    return str(words[key])


def _relation(actor: StageActor, others: Sequence[StageActor]) -> str:
    here = _ground(actor.position)
    partners = [other for other in others if other.name != actor.name and not other.crowd_id]
    if not partners:
        return ""
    other = min(partners, key=lambda item: geo.distance(here, _ground(item.position)))
    metres = geo.distance(here, _ground(other.position))
    if metres > _limit("near_pair_m"):
        return ""
    return _line("relation", other=other.name, m=_metres(metres))


def _shots_text(shot_ids: Sequence[int]) -> str:
    return "、".join(str(shot_id) for shot_id in shot_ids)


def _title(index: int, total: int, shot_ids: Sequence[int], moving: bool, mode: str = "") -> str:
    titles = _data()["titles"]
    head = str(titles["series"]).format(index=index, total=total)
    if len(shot_ids) == 1:
        span = str(titles["one_shot"]).format(shot=shot_ids[0])
    elif list(shot_ids) == list(range(shot_ids[0], shot_ids[-1] + 1)):
        span = str(titles["shot_span"]).format(first=shot_ids[0], last=shot_ids[-1])
    else:
        span = str(titles["shot_list"]).format(shots=_shots_text(shot_ids))
    if moving:
        kind = str(titles["move"])
    elif index == 1:
        kind = str(titles["opening"])
    elif index == total:
        kind = str(titles["closing"])
    else:
        kind = ""
    return " · ".join(part for part in (head, span, kind, mode) if part)


# --------------------------------------------------------------------------- one diagram


def _horizontal_fov(camera: StageCamera, lens_mm: float | None = None) -> float:
    aspect = geo.parse_aspect(camera.aspect)
    vertical = geo.vertical_fov(lens_mm or camera.lens_mm, aspect, camera.sensor_mm)
    return round(geo.horizontal_fov(vertical, aspect), 1)


def _piece_entry(piece: StageLandmark) -> dict[str, Any]:
    return {
        "name": piece.name, "kind": piece.kind, "shape": piece.shape,
        "position": [round(piece.position[0], 3), round(piece.position[1], 3)],
        "size": [round(value, 3) for value in piece.size], "yaw_deg": round(piece.yaw_deg, 1),
        "elevation_m": round(piece.elevation_m, 3),
    }


def _bounds(points: Sequence[Sequence[float]]) -> list[float]:
    if not points:
        return [-4.0, -4.0, 4.0, 4.0]
    xs, zs = [point[0] for point in points], [point[1] for point in points]
    low_x, low_z, high_x, high_z = min(xs) - 1.5, min(zs) - 1.5, max(xs) + 1.5, max(zs) + 1.5
    # Never a sliver: a duologue still gets a floor wide enough to read the grid.
    for low, high, index in ((low_x, high_x, 0), (low_z, high_z, 1)):
        if high - low < 6:
            pad = (6 - (high - low)) / 2
            if index == 0:
                low_x, high_x = low - pad, high + pad
            else:
                low_z, high_z = low - pad, high + pad
    return [math.floor(low_x), math.floor(low_z), math.ceil(high_x), math.ceil(high_z)]


def _drawn_camera(position: Sequence[float], content: Sequence[Sequence[float]]) -> tuple[list[float], float]:
    """Where a lens is drawn: its own ground point, pulled in when it stands far outside the action."""
    ground = _ground(position)
    centre = geo.centroid([_ground(point) for point in content]) if content else (0.0, 0.0)
    away = geo.distance(ground, centre)
    reach = _limit("camera_reach_m")
    spread = max([geo.distance(_ground(point), centre) for point in content] or [0.0])
    limit = spread + reach
    if away <= limit:
        return [round(ground[0], 3), round(ground[1], 3)], 0.0
    direction = geo.unit(geo.sub(ground, centre))
    drawn = geo.add(centre, geo.scale(direction, limit))
    return [round(drawn[0], 3), round(drawn[1], 3)], round(away, 1)


def _diagram(
    plan: StagePlan, shots: Sequence[StageShot], colors: Mapping[str, Mapping[str, str]],
    camera_numbers: Mapping[str, int], index: int, total: int, view: str,
) -> dict[str, Any]:
    lead = shots[0]
    starts = {actor.name: actor for actor in plan.actors_in(lead)}
    ends = {actor.name: actor for actor in plan.actors_in(lead, at_end=True)}
    staged = [ends.get(name, actor) for name, actor in starts.items()]
    extra_hex = str(_data()["extra_color"]["hex"])

    routes: list[dict[str, Any]] = []
    for name, first in starts.items():
        if first.crowd_id:
            continue
        points = _route(plan, lead, first, ends.get(name, first))
        if points:
            routes.append({
                "name": name, "color": colors[name]["hex"], "points": [[round(x, 3), round(z, 3)] for x, z in points],
                "meters": round(sum(geo.distance(a, b) for a, b in zip(points, points[1:])), 1),
                "starts_at_s": _first_move_time(plan, lead, name),
            })
    routes.sort(key=lambda item: item["starts_at_s"])
    for order, route in enumerate(routes, start=1):
        route["order"] = order
    route_of = {route["name"]: route for route in routes}

    figures: list[dict[str, Any]] = []
    for actor in staged:
        extra = bool(actor.crowd_id) or actor.role == "crowd"
        figures.append({
            "name": actor.name, "extra": extra, "role": actor.role,
            "color": extra_hex if extra else colors[actor.name]["hex"],
            "position": [round(actor.position[0], 3), round(actor.position[1], 3)],
            "yaw_deg": round(geo.normalize_yaw(actor.yaw_deg), 1), "posture": actor.posture,
            "posture_label": wording.posture_zh(actor.posture), "height_m": round(actor.height_m, 2),
            "start": route_of[actor.name]["points"][0] if actor.name in route_of else None,
        })

    set_pieces = [piece for piece in plan.landmarks_in(lead, at_end=True) if piece.kind != "light"]
    pieces = [_piece_entry(piece) for piece in set_pieces]
    # What a fight or an effect shot adds: strikes, reactions, effect ranges, the distances that matter.
    marks = action_marks.read(plan, shots, staged, colors, set_pieces, set(route_of))
    for route in routes:
        route.update(marks["route_kinds"].get(route["name"], {"kind": "walk", "label": ""}))
    for figure in figures:
        figure["acts"] = marks["acts"].get(figure["name"], [])
    content: list[Sequence[float]] = [figure["position"] for figure in figures]
    content += [point for route in routes for point in route["points"]]
    by_id = {camera.id: camera for camera in plan.cameras}

    cameras: list[dict[str, Any]] = []
    seen: set[str] = set()
    for shot in shots:
        for camera_id in (shot.camera_id, *shot.alt_camera_ids):
            camera = by_id.get(camera_id)
            if camera is None:
                continue
            if camera_id in seen:
                next(item for item in cameras if item["id"] == camera_id)["shot_ids"].append(shot.shot_id)
                continue
            seen.add(camera_id)
            drawn, far = _drawn_camera(camera.position, content)
            filming = camera_id == shot.camera_id
            subjects = [name for name in ((shot.subjects if filming else []) or camera.subjects) if name in starts]
            focus = subjects[0] if len(subjects) == 1 and not starts[subjects[0]].crowd_id else ""
            entry: dict[str, Any] = {
                "id": camera_id, "label": str(_data()["camera_label"]).format(camera_numbers[camera_id]),
                "position": drawn, "true_position": [round(camera.position[0], 3), round(camera.position[2], 3)],
                "height_m": round(camera.position[1], 2), "far_m": far,
                "target": [round(camera.target[0], 3), round(camera.target[2], 3)],
                "lens_mm": camera.equivalent_lens_mm, "fov_deg": _horizontal_fov(camera),
                "subjects": subjects, "focus": focus, "color": colors[focus]["hex"] if focus else "",
                "shot_ids": [shot.shot_id], "candidate": camera_id != shot.camera_id,
                "move": camera.move.kind, "move_label": wording.move_zh(camera.move.kind), "end_position": None,
            }
            if _camera_travels(camera):
                end = camera.move.end_position or camera.position
                entry["end_position"] = [round(end[0], 3), round(end[2], 3)]
            cameras.append(entry)

    footprint = [point for piece in pieces for point in _piece_corners(piece)]
    reach = [point for strike in marks["strikes"] for point in (strike["to"], strike["force_to"]) if point]
    for effect in marks["effects"]:
        x, z = effect["center"]
        reach += [[x - effect["radius_m"], z - effect["radius_m"]], [x + effect["radius_m"], z + effect["radius_m"]]]
    frame = [*content, *footprint, *reach, *[camera["position"] for camera in cameras],
             *[camera["end_position"] for camera in cameras if camera["end_position"]]]
    bounds = _bounds(frame)
    shot_ids = [shot.shot_id for shot in shots]
    title = _title(index, total, shot_ids, bool(routes), marks["mode_label"] if len(marks["modes"]) > 1 else "")
    notes = [_line("note_saved", revision=plan.revision)]
    if not cameras:
        notes.append(_line("note_no_camera"))
    diagram = {
        "index": index, "total": total, "shot_ids": shot_ids, "title": title, "view": view,
        "figures": figures, "pieces": pieces, "cameras": cameras, "routes": routes, "bounds": bounds,
        "notes": notes, "modes": marks["modes"], "mode_label": marks["mode_label"], "strikes": marks["strikes"],
        "effects": marks["effects"], "distances": marks["distances"], "nodes": marks["nodes"],
    }
    if any(item["source"] == "text" for item in marks["strikes"]) or any(item["read_from"] == "text" for item in marks["effects"]):
        notes.append(_line("note_text_marks"))
    diagram["legend"] = _legend(diagram, colors)
    diagram["prompt"] = _prompt(plan, diagram, colors, staged, view)
    return diagram


def _centre(diagram: Mapping[str, Any]) -> tuple[float, float]:
    low_x, low_z, high_x, high_z = diagram["bounds"]
    return ((low_x + high_x) / 2, (low_z + high_z) / 2)


def _legend(diagram: Mapping[str, Any], colors: Mapping[str, Mapping[str, str]]) -> list[dict[str, str]]:
    """The marks of the picture as a table kept outside it: mark, meaning, colour, where it points."""
    words = _data()["legend"]
    centre = _centre(diagram)
    grey = str(_data()["extra_color"]["name"])
    rows: list[dict[str, str]] = []

    def row(mark: str, meaning: str, color: str, where: str) -> None:
        rows.append({"mark": mark, "meaning": meaning, "color": color, "where": where})

    for figure in diagram["figures"]:
        if figure["extra"]:
            continue
        acts = str(words["acts"]).format(acts="、".join(figure["acts"])) if figure["acts"] else ""
        row(figure["name"], str(words["figure"]).format(posture=figure["posture_label"], acts=acts),
            colors[figure["name"]]["name"], _place(figure["position"], centre))
    extras = [figure for figure in diagram["figures"] if figure["extra"]]
    if extras:
        row(str(words["extras_mark"]), str(words["extras"]).format(count=len(extras)), grey,
            _place(geo.centroid([tuple(figure["position"]) for figure in extras]), centre))
    for camera in diagram["cameras"]:
        row(camera["label"], str(words["camera"]).format(lens=f"{camera['lens_mm']:g}", fov=f"{camera['fov_deg']:g}", shots=_shots_text(camera["shot_ids"])),
            colors[camera["focus"]]["name"] if camera["focus"] else grey, _place(camera["true_position"], centre))
    for route in diagram["routes"]:
        row(str(words["route_mark"]).format(order=route["order"]),
            str(words["route"]).format(name=route["name"], label=route["label"] or str(words["walk"]), m=_metres(route["meters"])),
            colors[route["name"]]["name"],
            str(words["span"]).format(start=_place(route["points"][0], centre), end=_place(route["points"][-1], centre)))
    for strike in diagram["strikes"]:
        meaning = (str(words["strike"]).format(attacker=strike["attacker"], target=strike["target"], m=_metres(strike["meters"]))
                   if strike["target"] else str(words["strike_open"]).format(attacker=strike["attacker"]))
        if strike["reaction"]:
            meaning += str(words["strike_reaction"]).format(target=strike["target"], reaction=strike["reaction"])
        row(strike["label"], meaning + str(words["source"]).format(source=strike["source_label"]),
            colors[strike["attacker"]]["name"], _place(strike["to"], centre))
    effect_color = action_marks.effect_color_name()
    for effect in diagram["effects"]:
        meaning = str(words["effect"]).format(name=effect["name"], r=_metres(effect["radius_m"]))
        if effect["source"]:
            meaning += str(words["effect_source"]).format(source=effect["source"])
        if effect["inside"]:
            meaning += str(words["effect_inside"]).format(names="、".join(effect["inside"]))
        row(effect["id"], meaning + str(words["source"]).format(source=effect["source_label"]), effect_color, _place(effect["center"], centre))
    for distance in diagram["distances"]:
        row(str(words["distance_mark"]), str(words["distance"]).format(a=distance["a"], b=distance["b"], m=_metres(distance["meters"])),
            str(words["ink"]), "")
    return rows


def _piece_corners(piece: Mapping[str, Any]) -> list[tuple[float, float]]:
    half_w, half_d = piece["size"][0] / 2, piece["size"][1] / 2
    centre = (piece["position"][0], piece["position"][1])
    forward = geo.forward_of(piece["yaw_deg"])
    right = geo.right_of(forward)
    return [
        geo.add(centre, geo.add(geo.scale(right, sx * half_w), geo.scale(forward, sz * half_d)))
        for sx, sz in ((-1, -1), (1, -1), (1, 1), (-1, 1))
    ]


# --------------------------------------------------------------------------- the text prompt


def _prompt(
    plan: StagePlan, diagram: Mapping[str, Any], colors: Mapping[str, Mapping[str, str]],
    staged: Sequence[StageActor], view: str,
) -> str:
    data = _data()
    heads = data["sections"]
    low_x, low_z, high_x, high_z = diagram["bounds"]
    centre = ((low_x + high_x) / 2, (low_z + high_z) / 2)
    width, depth = high_x - low_x, high_z - low_z
    by_name = {actor.name: actor for actor in staged}

    space = [_line("space", width=f"{width:g}", depth=f"{depth:g}", location=plan.location.strip())
             if plan.location.strip() else _line("space_bare", width=f"{width:g}", depth=f"{depth:g}"),
             str(data["place"]["origin_note"])]
    pieces = sorted(diagram["pieces"], key=lambda piece: piece["size"][0] * piece["size"][1] * piece["size"][2], reverse=True)
    piece_cap = int(_limit("piece_lines"))
    for piece in pieces[:piece_cap]:
        space.append(_line(
            "piece", name=piece["name"], place=_place(piece["position"], centre),
            w=_metres(piece["size"][0]), d=_metres(piece["size"][1]), h=_metres(piece["size"][2]),
            shape=str(data["shapes"].get(piece["shape"], data["shapes"]["box"])),
        ))
    if len(pieces) > piece_cap:
        space.append(_line("piece_more", count=len(pieces) - piece_cap))

    figure_lines: list[str] = []
    named = [figure for figure in diagram["figures"] if not figure["extra"]]
    named.sort(key=lambda figure: 0 if figure["role"] == "principal" else 1)
    figure_cap = int(_limit("figure_lines"))
    for figure in named[:figure_cap]:
        actor = by_name[figure["name"]]
        values = dict(
            name=figure["name"], color_name=colors[figure["name"]]["name"], hex=figure["color"],
            place=_place(figure["position"], centre), posture=figure["posture_label"],
            facing=_facing(actor, staged), relation=_relation(actor, staged),
        )
        if figure["start"]:
            figure_lines.append(_line("figure_start", start=_place(figure["start"], centre), **values))
        else:
            figure_lines.append(_line("figure", **values))
    if len(named) > figure_cap:
        figure_lines.append(_line("figure_more", count=len(named) - figure_cap))
    extras = [figure for figure in diagram["figures"] if figure["extra"]]
    if extras:
        middle = geo.centroid([tuple(figure["position"]) for figure in extras])
        figure_lines.append(_line("extras", count=len(extras), hex=str(data["extra_color"]["hex"]), place=_place(middle, centre)))

    path_lines = [
        _line(
            "path", order=route["order"], name=route["name"], color_name=colors[route["name"]]["name"],
            start=_place(route["points"][0], centre), end=_place(route["points"][-1], centre), m=_metres(route["meters"]),
            bends=_line("path_bends", count=len(route["points"]) - 2) if len(route["points"]) > 2 else "",
        ) + (_line("path_kind", label=route["label"]) if route.get("label") else "")
        for route in diagram["routes"]
    ]

    camera_lines: list[str] = []
    for camera in diagram["cameras"]:
        aim = (_line("aim_names", names="、".join(camera["subjects"])) if camera["subjects"]
               else _line("aim_point", place=_place(camera["target"], centre)))
        line = _line(
            "camera", label=camera["label"], place=_place(camera["true_position"], centre),
            height=_metres(camera["height_m"]), aim=aim, lens=f"{camera['lens_mm']:g}", fov=f"{camera['fov_deg']:g}",
            cone=_line("cone_focus", name=camera["focus"]) if camera["focus"] else _line("cone_plain"),
            shots=_line("camera_shots", shots=_shots_text(camera["shot_ids"])),
        )
        if camera["far_m"]:
            line += _line("camera_far", m=_metres(camera["far_m"]))
        camera_lines.append(line)
        if camera["end_position"]:
            camera_lines.append(_line("camera_move", label=camera["label"], move=camera["move_label"],
                                      place=_place(camera["end_position"], centre)))

    action_lines: list[str] = []
    for strike in diagram["strikes"]:
        color_name = colors[strike["attacker"]]["name"]
        if strike["target"]:
            force = _line("strike_force", target=strike["target"], reaction=strike["reaction"]) if strike["force_to"] else ""
            action_lines.append(_line("strike", label=strike["label"], attacker=strike["attacker"], target=strike["target"],
                                      color_name=color_name, m=_metres(strike["meters"]), force=force))
        else:
            action_lines.append(_line("strike_open", label=strike["label"], attacker=strike["attacker"], color_name=color_name,
                                      m=_metres(strike["meters"])))
    acting = [_line("act_item", name=figure["name"], acts="、".join(figure["acts"])) for figure in diagram["figures"] if figure.get("acts")]
    if acting:
        action_lines.append(_line("acts", items="；".join(acting)))
    # The ruler belongs with the staging: a plain diagram has one too.
    figure_lines += [_line("distance", a=item["a"], b=item["b"], m=_metres(item["meters"])) for item in diagram["distances"]]

    effect_lines = [
        _line(
            "effect", id=effect["id"], name=effect["name"], place=_place(effect["center"], centre), rings=effect["rings"],
            r=_metres(effect["radius_m"]),
            flow=_line("effect_flow", source=effect["source"]) if effect["from"] and effect["source"] else "",
            inside=_line("effect_inside", names="、".join(effect["inside"])) if effect["inside"] else "",
        )
        for effect in diagram["effects"]
    ]

    in_action = "action" in diagram["modes"]
    tag_names = _line("tag_names", names="、".join(figure["name"] for figure in named[:figure_cap])) if named else ""
    blocks: list[tuple[str, list[str]]] = [
        (str(heads["view"]), [str(data["views"][view]["line"]), _line("moment")]),
        (str(heads["space"]), space),
        (str(heads["figures"]), figure_lines),
    ]
    if path_lines:
        blocks.append((str(heads["paths"]), path_lines))
    if action_lines:
        blocks.append((str(heads["actions"]), action_lines))
    if effect_lines:
        blocks.append((str(heads["effects"]), effect_lines))
    if camera_lines:
        blocks.append((str(heads["cameras"]), camera_lines))
    blocks += [
        (str(heads["tags"]), [_line("tags", names=tag_names)]),
        (str(heads["render"]), [_line("render_action" if in_action else "render")]),
        (str(heads["avoid"]), [_line("avoid")]),
    ]
    head = str(heads["head"]).format(title=diagram["title"])

    def render() -> str:
        return "\n".join([head, *[part for title, lines in blocks if lines for part in ("", title, *lines)]])

    # Too long: the set dressing goes first, the people last; the look and the cameras stay.
    cap = int(_limit("prompt_chars"))
    text = render()
    while len(text) > cap and len(space) > 2:
        space.pop()
        text = render()
    while len(text) > cap and len(figure_lines) > 2:
        figure_lines.pop()
        text = render()
    return text[:cap]


# --------------------------------------------------------------------------- the series


def build(plan: StagePlan, view: str = "") -> dict[str, Any]:
    """Every staging beat of the scene as a diagram, in shot order."""
    known = views()
    view = view or default_view()
    if view not in known:
        raise BlockingDiagramError(str(_data()["errors"]["unknown_view"]).format(view=view, views=" / ".join(known)))
    if not plan.shots:
        raise BlockingDiagramError(str(_data()["errors"]["no_shots"]))
    colors = assign_colors(plan.actors)
    numbers: dict[str, int] = {}
    for shot in plan.shots:
        for camera_id in (shot.camera_id, *shot.alt_camera_ids):
            numbers.setdefault(camera_id, len(numbers) + 1)
    beats = _beats(plan)
    diagrams = [_diagram(plan, shots, colors, numbers, index, len(beats), view) for index, shots in enumerate(beats, start=1)]
    return {
        "scene_id": plan.scene_id, "location": plan.location, "revision": plan.revision, "view": view,
        "views": [{"id": key, **item} for key, item in known.items()],
        "grid": {"cell_m": 1, "major_every": 5},
        "colors": [{"name": name, "hex": value["hex"], "color_name": value["name"]} for name, value in colors.items()
                   if not any(actor.name == name and (actor.crowd_id or actor.role == "crowd") for actor in plan.actors)],
        "extra_color": str(_data()["extra_color"]["hex"]),
        "diagrams": diagrams,
    }


__all__ = ["BlockingDiagramError", "assign_colors", "build", "default_view", "views"]
