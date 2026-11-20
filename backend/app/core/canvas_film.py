# -*- coding: utf-8 -*-
"""One finished film from the canvas: the shots' clips in order, a voice for each silent clip that has lines,
music if asked, all joined by one compose node that the canvas then runs together with whatever is still missing.

Which clips: the ones the person picked; otherwise every video node bound to a storyboard shot, in storyboard
order (one per shot: the one that already has a result, else the one the layout made); otherwise, on a canvas
with no storyboard behind it, every video node from left to right, row by row.

Voices follow the project's rule that a clip keeps the sound its video model made: a clip that has come back
with sound gets no voice, nor does one whose model makes sound. Only a silent clip with lines is voiced, by
reading those lines the way stage 6 does (each speaker in that character's voice). The compose node remembers
which voice belongs to which clip (``soundPlan``), and at compose time a voice is laid only under a clip that
turned out silent.

Running a second time reuses the film's own nodes (marked ``payload.film``): the compose node is rewired in the
new order, a voice or the music already made is kept. Wording and layout: ``canvas_film.json``.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping, Sequence
from typing import Any

from app.core import canvas_storyboard, prompt_data, studio_canvas

_DATA = "canvas_film"
#: The payload key on the nodes this builder owns: ``{"role": "compose" | "voice" | "music", "clip"?: node id}``.
MARK = "film"
#: The compose node's note of which voice belongs to which clip, and which input is the music.
SOUND_PLAN = "soundPlan"

_EMPTY_LINES = ("无", "-", "—", "（无）", "无台词")


class FilmError(ValueError):
    """No film can be put together as asked; the message is for the person."""


def _text(key: str) -> str:
    return prompt_data.text(_DATA, key)


def _payload(node: Mapping[str, Any]) -> dict[str, Any]:
    payload = node.get("payload")
    return payload if isinstance(payload, dict) else {}


def _mark(node: Mapping[str, Any]) -> dict[str, Any]:
    mark = _payload(node).get(MARK)
    return mark if isinstance(mark, Mapping) else {}


def _binding(node: Mapping[str, Any]) -> tuple[str, int] | None:
    binding = _payload(node).get("binding")
    if not isinstance(binding, Mapping) or not str(binding.get("sceneId") or "").strip():
        return None
    try:
        shot = int(binding.get("shotId") or 0)
    except (TypeError, ValueError):
        return None
    return (str(binding["sceneId"]).strip(), shot) if shot > 0 else None


def _label(node: Mapping[str, Any]) -> str:
    return str(_payload(node).get("label") or node.get("id") or "")


# ---------------------------------------------------------------------------------------------- which clips, in what order


def film_clips(task: Mapping[str, Any], document: Mapping[str, Any], *, picked: Collection[str] = (), has_output: Callable[[str], bool]) -> list[dict[str, Any]]:
    """The clips of the film, in the order they play."""
    order = {(shot["scene_id"], shot["shot_id"]): index for index, shot in enumerate(canvas_storyboard._shots(task))}  # noqa: SLF001
    videos = [node for node in document.get("nodes") or [] if isinstance(node, dict) and node.get("kind") == "video_gen"]
    chosen = set(picked)
    if chosen:
        videos = [node for node in videos if str(node.get("id")) in chosen]
    else:
        bound = [node for node in videos if _binding(node) in order]
        if bound:
            videos = bound

    def key(node: Mapping[str, Any]) -> tuple:
        bound = _binding(node)
        place = order.get(bound) if bound else None
        return (0, place, 0.0, 0.0) if place is not None else (1, 0, float(node.get("y") or 0), float(node.get("x") or 0))

    clips: list[dict[str, Any]] = []
    seen: dict[tuple[str, int], int] = {}
    for node in sorted(videos, key=key):
        bound = _binding(node)
        if bound in order and not chosen:
            # One clip per shot: a copy somebody made to try again does not play twice.
            if bound in seen:
                held = clips[seen[bound]]
                if not has_output(str(held["id"])) and has_output(str(node["id"])):
                    clips[seen[bound]] = node
                continue
            seen[bound] = len(clips)
        clips.append(node)
    return clips


def lines_of(task: Mapping[str, Any], clip: Mapping[str, Any]) -> str:
    """The lines spoken in this clip: its storyboard shot's dialogue, or what its text gives after the lines lead."""
    shots = {(shot["scene_id"], shot["shot_id"]): shot for shot in canvas_storyboard._shots(task)}  # noqa: SLF001
    bound = _binding(clip)
    if bound in shots:
        cell = str(shots[bound].get("dialogue") or "").strip()
    else:
        prompt = str(_payload(clip).get("prompt") or "")
        lead = prompt_data.text("canvas_storyboard", "dialogue_lead")
        cell = prompt.split(lead, 1)[1].strip() if lead in prompt else ""
    return "" if cell in _EMPTY_LINES else cell[: prompt_data.number(_DATA, "max_line_chars")]


def _seconds(clip: Mapping[str, Any]) -> int:
    params = _payload(clip).get("params") if isinstance(_payload(clip).get("params"), Mapping) else {}
    try:
        return max(1, int(params.get("durationSeconds") or 5))
    except (TypeError, ValueError):
        return 5


# ---------------------------------------------------------------------------------------------- the plan


def plan(
    task: Mapping[str, Any],
    document: Mapping[str, Any],
    *,
    picked: Collection[str] = (),
    voices: bool = True,
    music: bool = False,
    music_prompt: str = "",
    has_output: Callable[[str], bool],
    needs_voice: Callable[[Mapping[str, Any]], bool],
) -> dict[str, Any]:
    """The edit that puts the film together, and what then has to run.

    ``{"operations", "marks", "sound_plan", "compose", "run", "clips", "voiced", "music", "missing"}``: ``marks`` and
    ``sound_plan`` name nodes by ref or id and are applied after the operations; ``run`` lists the refs or ids to
    run, upstream first is not needed (the runner orders a batch itself).
    """
    clips = film_clips(task, document, picked=picked, has_output=has_output)
    if not clips:
        raise FilmError(_text("no_clips"))
    limit = prompt_data.number(_DATA, "max_clips")
    if len(clips) > limit:
        raise FilmError(_text("too_many").format(limit=limit, count=len(clips)))

    nodes = [node for node in document.get("nodes") or [] if isinstance(node, dict)]
    edges = [edge for edge in document.get("edges") or [] if isinstance(edge, Mapping)]
    by_id = {str(node.get("id")): node for node in nodes}
    grid = prompt_data.value(_DATA, "layout")
    owned = {role: [node for node in nodes if _mark(node).get("role") == role] for role in ("compose", "voice", "music")}
    voice_for = {str(_mark(node).get("clip") or ""): node for node in owned["voice"]}

    operations: list[dict[str, Any]] = []
    marks: dict[str, dict[str, Any]] = {}
    laid = [node for node in nodes if node.get("kind") != "group"]
    right = max((float(node.get("x") or 0) + float(node.get("width") or 0) for node in laid), default=0.0)
    top = min((float(node.get("y") or 0) for node in laid), default=0.0)
    voice_x = right + grid["margin"]
    compose_x = voice_x + grid["voice_width"] + grid["gap"] * 3

    compose = owned["compose"][0] if owned["compose"] else None
    if compose is not None:
        compose_ref = str(compose["id"])
        # The film is rewired in this order: what fed it before is let go first.
        for edge in edges:
            if str(edge.get("target")) == compose_ref:
                operations.append({"op": "disconnect", "edge_id": edge.get("id"), "source": edge.get("source"), "target": edge.get("target")})
    else:
        compose_ref = "film_compose"
        width, height = grid["compose_size"]
        operations.append({"op": "add_node", "ref": compose_ref, "kind": "video_compose", "label": _text("compose_label"),
                           "x": compose_x, "y": top + grid["music_size"][1] + grid["gap"] * 2, "width": width, "height": height})
        marks[compose_ref] = {"role": "compose"}

    for clip in clips:
        operations.append({"op": "connect", "source": clip["id"], "target": compose_ref, "role": "clip"})

    sound_voices: dict[str, str] = {}
    run: list[str] = []
    voiced = 0
    row = 0
    for clip in clips:
        clip_id = str(clip["id"])
        cell = lines_of(task, clip) if voices else ""
        if not cell or not needs_voice(clip):
            continue
        voiced += 1
        held = voice_for.get(clip_id)
        if held is not None:
            ref = str(held["id"])
            if not has_output(ref) and str(_payload(held).get("prompt") or "") != cell:
                operations.append({"op": "update_node", "id": ref, "prompt": cell})
        else:
            ref = f"film_voice_{len(sound_voices)}"
            width, height = grid["voice_size"]
            operations.append({
                "op": "add_node", "ref": ref, "kind": "audio_gen", "label": _text("voice_label").format(label=_label(clip)), "prompt": cell,
                # castLines: the text is read as 「名字：台词」 lines, each speaker in the project's voice for them.
                "params": {"mode": "speech", "castLines": True},
                "x": voice_x, "y": top + row * (height + grid["gap"]), "width": width, "height": height,
            })
            marks[ref] = {"role": "voice", "clip": clip_id}
            row += 1
        operations.append({"op": "connect", "source": ref, "target": compose_ref, "role": "soundtrack"})
        sound_voices[clip_id] = ref
        if not has_output(ref):
            run.append(ref)

    music_ref = ""
    if music:
        held = owned["music"][0] if owned["music"] else None
        total = sum(_seconds(clip) for clip in clips)
        seconds = max(prompt_data.number(_DATA, "min_music_seconds"), min(prompt_data.number(_DATA, "max_music_seconds"), total))
        prompt = " ".join(str(music_prompt or "").split())[:400] or _text("music_prompt")
        if held is not None:
            music_ref = str(held["id"])
            if not has_output(music_ref):
                operations.append({"op": "update_node", "id": music_ref, "prompt": prompt, "params": {"mode": "music", "durationSeconds": seconds}})
        else:
            music_ref = "film_music"
            width, height = grid["music_size"]
            operations.append({"op": "add_node", "ref": music_ref, "kind": "audio_gen", "label": _text("music_label"), "prompt": prompt,
                               "params": {"mode": "music", "durationSeconds": seconds}, "x": compose_x, "y": top, "width": width, "height": height})
            marks[music_ref] = {"role": "music"}
        operations.append({"op": "connect", "source": music_ref, "target": compose_ref, "role": "soundtrack"})
        if not has_output(music_ref):
            run.append(music_ref)

    # Whatever a clip still waits for upstream (a first frame to draw, a tool to run) goes in the same batch.
    # frames: first frames a clip opens on; pictures: everything else drawn on the way (a character's look sheet).
    missing = {"frames": 0, "pictures": 0, "clips": 0}
    waiting: list[str] = []
    seen: set[str] = set()

    def walk(node_id: str) -> None:
        for edge in edges:
            source = str(edge.get("source"))
            if str(edge.get("target")) != node_id or source in seen or source not in by_id:
                continue
            seen.add(source)
            upstream = by_id[source]
            if studio_canvas.medium_of(upstream) is not None and not has_output(source):
                waiting.append(source)
                if upstream.get("kind") == "image_gen":
                    opens = (edge.get("payload") or {}).get("role") == "first_frame" and by_id.get(node_id, {}).get("kind") == "video_gen"
                    missing["frames" if opens else "pictures"] += 1
            walk(source)

    for clip in clips:
        clip_id = str(clip["id"])
        if not has_output(clip_id):
            waiting.append(clip_id)
            missing["clips"] += 1
        walk(clip_id)
    run = list(dict.fromkeys(waiting + run + [compose_ref]))
    return {
        "operations": operations, "marks": marks, "compose": compose_ref,
        "sound_plan": {"voices": sound_voices, **({"music": music_ref} if music_ref else {})},
        "run": run, "clips": [str(clip["id"]) for clip in clips], "voiced": voiced, "music": bool(music_ref),
        "missing": {**missing, "voices": sum(1 for ref in sound_voices.values() if not has_output(ref)),
                    "music": int(bool(music_ref) and not has_output(music_ref))},
    }


def describe(task: Mapping[str, Any], document: Mapping[str, Any], clips: Sequence[str]) -> list[dict[str, Any]]:
    """The film's shots as the dialog lists them: label, binding, length and lines."""
    by_id = {str(node.get("id")): node for node in document.get("nodes") or [] if isinstance(node, Mapping)}
    rows = []
    for clip_id in clips:
        node = by_id[clip_id]
        bound = _binding(node)
        rows.append({"node_id": clip_id, "label": _label(node), "scene": bound[0] if bound else "", "shot": bound[1] if bound else 0,
                     "seconds": _seconds(node), "lines": lines_of(task, node)})
    return rows


__all__ = ["FilmError", "MARK", "SOUND_PLAN", "describe", "film_clips", "lines_of", "plan"]
