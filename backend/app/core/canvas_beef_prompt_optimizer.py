"""Tidy the prompt of a canvas picture or clip node into one a generation model can follow.

Nine ways: expand a vague idea, refine an existing prompt, strengthen the style, fit the target model,
work in the node's connected references (their text; pictures are counted, not described, since the text
model does not see them), rewrite into one of three fixed layouts (``prompt_structure``: eight sections
with a timed shot script, a fight's action line, a performance written as measured movements), or
diagnose and rewrite the camera only (``camera_doctor`` checks the prompt
first and its findings ride along). One text call returns a structured result: the prompt, what to avoid, what was
changed, what was assumed, and optional alternatives. A missing or malformed result is an error and the
node's prompt is left as it was; only the person adopting the result changes it.

A clip node's prompt gets one camera move, sized by how far the frame has moved at the final framing, as
the project plans its shots. The method, the per-mode rule, the clip rule, the output contract (last, never
left out), limits and messages are in
``app/data/prompt/canvas_beef_prompt_optimizer.json``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Sequence

from app.core import camera_doctor, prompt_data, prompt_structure
from app.core.screenwriting.structured_llm import extract_json_object

_DATA = "canvas_beef_prompt_optimizer"
MODES = ("expand", "refine", "style", "fit_model", "references", "structure", "fight", "performance", "camera")
# The modes that rewrite into a fixed layout (prompt_structure); the mode id is the layout id.
LAYOUT_MODES = frozenset(prompt_structure.layouts())
MEDIA = ("image", "video")


class OptimizerError(ValueError):
    """The request cannot be optimized, or the model's answer cannot be used; the prompt stays as it was."""


@dataclass(frozen=True)
class Request:
    prompt: str
    medium: str
    mode: str
    target_model: str = ""
    references: Sequence[str] = ()
    image_references: int = 0
    note: str = ""
    # The clip's length in seconds when the node gives one; only the fixed-layout modes read it.
    duration: float = 0.0


@dataclass(frozen=True)
class Result:
    prompt: str
    avoid: list[str] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    alternatives: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"prompt": self.prompt, "avoid": self.avoid, "changes": self.changes,
                "assumptions": self.assumptions, "alternatives": self.alternatives}


def _rules() -> dict[str, Any]:
    return prompt_data.load(_DATA)


def _limit(key: str) -> int:
    return int(_rules()["limits"][key])


def _error(key: str, **values: object) -> OptimizerError:
    return OptimizerError(str(_rules()["errors"][key]).format(**values))


def modes() -> list[dict[str, str]]:
    return [{"id": mode, "label": str(_rules()["modes"][mode]["label"])} for mode in MODES]


def _text(value: Any, limit: int) -> str:
    clean = "".join(ch for ch in str(value or "") if ch in "\n\t" or ch.isprintable()).strip()
    return clean[:limit]


def checked(request: Request) -> Request:
    """``request`` cleaned and within limits, or :class:`OptimizerError` saying what is wrong."""
    if request.mode not in MODES:
        raise _error("unknown_mode", mode=request.mode)
    if request.medium not in MEDIA:
        raise _error("unknown_medium")
    prompt = "".join(ch for ch in str(request.prompt or "") if ch in "\n\t" or ch.isprintable()).strip()
    if not prompt:
        raise _error("empty_prompt")
    if len(prompt) > _limit("prompt_chars"):
        raise _error("prompt_too_long", limit=_limit("prompt_chars"), length=len(prompt))
    references = [
        text for text in (_text(item, _limit("reference_chars")) for item in request.references) if text
    ][: _limit("references")]
    images = max(0, int(request.image_references or 0))
    if request.mode == "references" and not references and not images:
        raise _error("references_needed")
    if request.mode in LAYOUT_MODES and request.medium != "video" and prompt_structure.video_only(request.mode):
        raise OptimizerError(prompt_structure.video_only_error(request.mode))
    return Request(
        prompt=prompt, medium=request.medium, mode=request.mode, target_model=_text(request.target_model, 120),
        references=tuple(references), image_references=images, note=_text(request.note, _limit("note_chars")),
        duration=prompt_structure.clip_seconds(request.duration),
    )


def prompts(request: Request) -> tuple[str, str]:
    """System prompt (method, the mode's rule, then the contract) and user prompt for a checked request."""
    rules = _rules()
    target = request.target_model or str(rules["unknown_target"])
    medium = str(rules["media"][request.medium])
    rule = str(rules["modes"][request.mode]["rule"]).format(target_model=target)
    method = str(rules["system"]).format(medium=medium, mode_rule=rule)
    if request.mode in LAYOUT_MODES:
        # A fixed layout with a timed script: its sections and rules, with the one-move rule applied per segment.
        method += "\n\n" + prompt_structure.guide(request.duration, request.mode, request.medium)
    elif request.medium == "video":
        # One camera move per clip, as the project's shots are planned (camera_motion.py).
        method += "\n" + str(rules["video_rules"])
    if request.mode == "camera":
        # The four checks and the emotion table (camera_doctor); the clip rule above still sizes the move.
        method += "\n\n" + camera_doctor.guide()
    system = method + "\n\n" + str(rules["contract"])
    references = ""
    if request.references or request.image_references:
        references = str(rules["references_heading"]) + "".join(
            str(rules["reference_line"]).format(text=text.replace("\n", " ")) for text in request.references
        )
        if request.image_references:
            references += str(rules["image_reference_note"]).format(count=request.image_references)
    note = str(rules["note_heading"]).format(note=request.note) if request.note else ""
    user = str(rules["user"]).format(medium=medium, target_model=target, prompt=request.prompt, references=references, note=note)
    if request.mode == "camera":
        user += camera_doctor.findings_block(camera_doctor.diagnose(request.prompt, request.medium))
    return system, user


def _items(raw: Any, limit: int) -> list[str]:
    if not isinstance(raw, list):
        return []
    found = [re.sub(r"\s+", " ", str(item)).strip()[: _limit("item_chars")] for item in raw if isinstance(item, (str, int, float))]
    return list(dict.fromkeys(item for item in found if item))[:limit]


def parse(answer: str) -> Result:
    """The structured result of an answer, or :class:`OptimizerError` (the prompt is then left unchanged)."""
    if not str(answer or "").strip():
        raise _error("no_answer")
    found = extract_json_object(answer)
    if not isinstance(found, dict):
        raise _error("not_object")
    prompt = _text(found.get("prompt"), _limit("result_chars"))
    if not prompt:
        raise _error("empty_result")
    alternatives = [
        text for text in (_text(item, _limit("result_chars")) for item in (found.get("alternatives") or []) if isinstance(item, str))
        if text and text != prompt
    ][: _limit("alternatives")]
    return Result(
        prompt=prompt, avoid=_items(found.get("avoid"), _limit("list_items")),
        changes=_items(found.get("changes"), _limit("list_items")),
        assumptions=_items(found.get("assumptions"), _limit("list_items")), alternatives=alternatives,
    )
