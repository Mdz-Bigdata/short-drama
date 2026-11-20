# -*- coding: utf-8 -*-
"""A review report of a finished script: seven aspects, each with a verdict, and findings that point at a scene.

The project's text model reads the script the way the submission pack lays it out (episodes, numbered
scenes, action lines, spoken lines) and answers in a fixed shape: a short overall judgement, one verdict
per aspect, findings (which aspect, how serious, which scene, a quoted line, what is wrong, how to change
it) and a few strengths. The report is advice for the creator. It changes nothing in the script and
gates nothing.

What keeps it honest:

* a finding's scene number must be one the reviewed block really has, or empty for the whole script;
  anything else is sent back to the model with the reason;
* a quoted line that is not in the script is removed (the finding stays) and counted;
* the production facts (episodes, scenes, places, speaking characters, share of dialogue) are counted
  from the script without a model.

A long script is read in blocks of whole episodes, one call per block; each block then also gets the
whole series' digest so that cause and effect across episodes can be judged. Blocks are merged by taking
the worst verdict per aspect. The model is called only when the creator asks for a report.
Wording, aspects and limits are data (``app/data/prompt/script_review.json``).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from app.core import prompt_data, submission_pack
from app.core.screenwriting.structured_llm import LLMCaller, call_structured

_DATA = "script_review"
ASSET_KEY = "2_script_review"
STORE_VERSION = 1
# How often one block may be asked: an answer in the wrong shape is sent back with the reasons.
ATTEMPTS = 3


class ScriptReviewError(ValueError):
    """A review that cannot be made: no script, or a script longer than one run reads."""


def _data() -> Mapping[str, Any]:
    return prompt_data.load(_DATA)


def _limit(key: str) -> int:
    return int(_data()["limits"][key])


def _keys(table: str) -> list[str]:
    return [str(item["key"]) for item in _data()[table]]


def _label(table: str, key: str) -> str:
    return next((str(item["label"]) for item in _data()[table] if item["key"] == key), key)


def _clean(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def error(key: str, **values: object) -> ScriptReviewError:
    return ScriptReviewError(str(_data()["errors"][key]).format(**values))


def offline_text() -> str:
    return str(_data()["model"]["offline"])


# --------------------------------------------------------------------------- the full review and the focused checks


def focuses() -> list[dict[str, str]]:
    """What can be asked for: the full review first (key ``""``), then the focused checks."""
    full = _data()["full"]
    return [{"key": "", "label": str(full["label"]), "about": str(full["about"])},
            *[{"key": str(item["key"]), "label": str(item["label"]), "about": str(item["about"])} for item in _data()["focuses"]]]


def _focus(focus: str) -> Mapping[str, Any]:
    """The table of one focused check; the full review reads as a check with the seven aspects and no limits."""
    if not focus:
        return {"key": "", "label": _data()["full"]["label"], "episodes": 0, "bios": False, "dimensions": _data()["dimensions"]}
    found = next((item for item in _data()["focuses"] if item["key"] == focus), None)
    if found is None:
        raise ScriptReviewError(str(_data()["focus_words"]["unknown"]).format(focus=focus))
    return found


def asset_key(focus: str = "") -> str:
    return f"{ASSET_KEY}_{_focus(focus)['key']}" if focus else ASSET_KEY


def _dimensions(focus: str) -> list[Mapping[str, Any]]:
    return list(_focus(focus)["dimensions"])


def _dimension_keys(focus: str) -> list[str]:
    return [str(item["key"]) for item in _dimensions(focus)]


def _dimension_label(focus: str, key: str) -> str:
    return next((str(item["label"]) for item in _dimensions(focus) if item["key"] == key), key)


def _count_word(count: int) -> str:
    return str(_data()["count_words"].get(str(count), count))


def bios_of(task: Mapping[str, Any]) -> str:
    """The character sheet the lines are held against: one line per named character, lead first."""
    words = _data()["focus_words"]
    limit = int(words["bio_chars"])
    lines = []
    for name, facts_ in submission_pack.roster(task).items():
        text = _clean(facts_.get("description") or facts_.get("desc") or "", limit)
        if text:
            lines.append(str(words["bio_line"]).format(name=name, text=text))
    return "\n".join(lines)


# --------------------------------------------------------------------------- the script as the model reads it


def _scene_number(heading: str) -> str:
    return heading.split()[0] if heading.split() else ""


def episodes_of(task: Mapping[str, Any], scenes: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Each episode as ``{episode, text, numbers}``: its script text and the scene numbers in it."""
    rows: list[dict[str, Any]] = []
    # The caption marks are the submission template's layout, not script: the reviewer should not read or quote them.
    marks = re.compile(str(_data()["strip_marks"]))
    voices = _unnamed_voices(scenes)
    for episode in submission_pack.script_body(task, scenes):
        raw_lines = submission_pack.body_lines([episode])
        lines = []
        for raw in raw_lines:
            # A voice with no name keeps what the script says about it, in script order.
            noted = voices.get(raw)
            lines.append(noted.pop(0) if noted else marks.sub("", raw))
        text = "\n".join(line for line, raw in zip(lines, raw_lines) if line.strip() or not raw.strip()).strip()
        numbers = [number for number in (_scene_number(str(scene.get("heading") or "")) for scene in episode.get("scenes") or []) if number]
        rows.append({"episode": int(episode["episode"]), "text": text, "numbers": numbers})
    return rows


def _unnamed_voices(scenes: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
    """Spoken lines with no speaker whose delivery says whose voice it is: the template's line → that line with the note, in script order."""
    words = _data()["unnamed_voice"]
    split = re.compile(str(words["split"]))
    noted: dict[str, list[str]] = {}
    for scene in scenes:
        for item in (scene.get("dialogue") or []) if isinstance(scene, Mapping) else []:
            if not isinstance(item, Mapping) or (item.get("kind") == "dialogue" and str(item.get("speaker") or "").strip()):
                continue
            plain = submission_pack.dialogue_line(item)
            note = next((part.strip() for part in split.split(str(item.get("delivery") or "")) if part.strip()), "")[: int(words["note_chars"])]
            # Every unnamed line takes its turn, noted or not, so a repeated line keeps its own note.
            noted.setdefault(plain, []).append(str(words["line"]).format(note=note, text=" ".join(str(item.get("text") or "").split())) if plain and note else plain)
    return noted


def blocks(episodes: Sequence[Mapping[str, Any]]) -> list[list[Mapping[str, Any]]]:
    """Whole episodes packed into blocks under the character budget; an episode longer than the budget is a block alone."""
    budget = _limit("block_chars")
    packed: list[list[Mapping[str, Any]]] = []
    size = 0
    for episode in episodes:
        length = len(str(episode["text"]))
        if packed and size + length <= budget:
            packed[-1].append(episode)
            size += length
        else:
            packed.append([episode])
            size = length
    return packed


def reviewed(task: Mapping[str, Any], scenes: Sequence[Mapping[str, Any]], focus: str = "") -> list[dict[str, Any]]:
    """The episodes this review reads: all of them, or the first few for a check that only looks at the opening."""
    episodes = episodes_of(task, scenes)
    first = int(_focus(focus).get("episodes") or 0)
    return episodes[:first] if first else episodes


def calls_needed(task: Mapping[str, Any], scenes: Sequence[Mapping[str, Any]], focus: str = "") -> int:
    """How many text-model calls one report takes: one per block."""
    return len(blocks(reviewed(task, scenes, focus)))


def fingerprint(task: Mapping[str, Any], scenes: Sequence[Mapping[str, Any]], focus: str = "") -> str:
    """What the report was written from: the episodes it read, and the character sheet when it was held against one."""
    text = "\n".join(str(episode["text"]) for episode in reviewed(task, scenes, focus))
    if _focus(focus).get("bios"):
        text += "\n" + bios_of(task)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def facts(task: Mapping[str, Any], scenes: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """What can be counted from the script without a model, as ``[{key, label, value}]``."""
    body = submission_pack.script_body(task, scenes)
    labels = _data()["facts"]["labels"]
    places = {str(scene.get("heading") or "").split()[1] for episode in body for scene in episode.get("scenes") or []
              if len(str(scene.get("heading") or "").split()) > 1}
    spoken = [item for scene in scenes if isinstance(scene, Mapping) for item in scene.get("dialogue") or []
              if isinstance(item, Mapping) and item.get("kind") == "dialogue" and str(item.get("text") or item.get("line") or "").strip()]
    speakers = {str(item.get("speaker") or "").strip() for item in spoken if str(item.get("speaker") or "").strip()}
    spoken_chars = sum(len(str(item.get("text") or item.get("line") or "")) for item in spoken)
    total = sum(len(str(episode["text"])) for episode in episodes_of(task, scenes))
    share = round(100 * spoken_chars / total) if total else 0
    values = {
        "episodes": str(len(body)), "scenes": str(sum(len(episode.get("scenes") or []) for episode in body)),
        "places": str(len(places)), "speakers": str(len(speakers)), "lines": str(len(spoken)),
        "dialogue_share": str(_data()["facts"]["percent"]).format(value=share), "chars": str(total),
    }
    return [{"key": key, "label": str(labels[key]), "value": values[key]} for key in labels]


# --------------------------------------------------------------------------- what the model writes


class _Verdict(BaseModel):
    key: str = Field("", max_length=40)
    verdict: str = Field("", max_length=40)
    note: str = Field("", max_length=600)


class _Finding(BaseModel):
    dimension: str = Field("", max_length=40)
    severity: str = Field("", max_length=40)
    scene: str = Field("", max_length=40)
    quote: str = Field("", max_length=400)
    issue: str = Field("", max_length=1200)
    fix: str = Field("", max_length=1200)


class _Review(BaseModel):
    summary: str = Field("", max_length=2000)
    dimensions: list[_Verdict] = Field(default_factory=list)
    findings: list[_Finding] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)


def _options(table: str) -> str:
    words = _data()["model"]
    return str(words["option_joiner"]).join(str(words["option"]).format(key=item["key"], label=item["label"]) for item in _data()[table])


def _validator(numbers: Sequence[str], focus: str = ""):
    """Reasons to send the answer back: aspects missing or unknown, a verdict or a weight outside its list, a scene not in this block."""
    problems = _data()["problems"]
    keys, verdicts, severities = _dimension_keys(focus), _keys("verdicts"), _keys("severities")
    known = set(numbers)

    def check(data: dict[str, Any]) -> list[str]:
        reasons: list[str] = []
        got = [str(item.get("key") or "") for item in data.get("dimensions") or []]
        if sorted(got) != sorted(keys):
            reasons.append(str(problems["dimensions"]).format(keys=" / ".join(keys), count=_count_word(len(keys))))
        for item in data.get("dimensions") or []:
            if item.get("key") in keys and item.get("verdict") not in verdicts:
                reasons.append(str(problems["verdict"]).format(key=item.get("key"), options=" / ".join(verdicts)))
        # More findings than asked for are cut, not sent back: the first ones are the ones that matter.
        data["findings"] = list(data.get("findings") or [])[: _limit("max_findings")]
        for index, finding in enumerate(data["findings"], start=1):
            finding["scene"] = str(finding.get("scene") or "").strip()
            if finding.get("dimension") not in keys:
                reasons.append(str(problems["finding_dimension"]).format(index=index, keys=" / ".join(keys)))
            if finding.get("severity") not in severities:
                reasons.append(str(problems["finding_severity"]).format(index=index, options=" / ".join(severities)))
            if finding["scene"] and finding["scene"] not in known:
                reasons.append(str(problems["finding_scene"]).format(index=index, scene=finding["scene"], scenes=" / ".join(numbers)))
            if not str(finding.get("issue") or "").strip() or not str(finding.get("fix") or "").strip():
                reasons.append(str(problems["finding_empty"]).format(index=index))
        return reasons

    return check


_SPACE = re.compile(r"\s+")


def _in_script(quote: str, script: str) -> bool:
    return bool(quote) and _SPACE.sub("", quote) in _SPACE.sub("", script)


def block_prompts(
    block: Sequence[Mapping[str, Any]], *, total: int, digest: str = "", focus: str = "", bios: str = "", series: int = 0,
) -> tuple[str, str]:
    """``(system, user)`` for one block of episodes. ``series`` is the whole series' length when the review reads only its first episodes."""
    words = _data()["model"]
    first, last = int(block[0]["episode"]), int(block[-1]["episode"])
    whole = len(block) == total
    if whole and series > total:
        scope = str(_data()["focus_words"]["scope_first"]).format(count=total, episodes=series)
    else:
        scope = (str(words["scope_whole"]).format(episodes=total) if whole
                 else str(words["scope_one" if first == last else "scope_block"]).format(first=first, last=last, episodes=total))
    dimensions = _dimensions(focus)
    sheet = str(_data()["focus_words"]["bios"]).format(bios=bios) if bios else ""
    numbers = [number for episode in block for number in episode["numbers"]]
    system = str(words["system"]).format(
        quote_chars=_limit("quote_chars"), max_findings=_limit("max_findings"), max_strengths=_limit("max_strengths"),
    )
    user = str(words["task"]).format(
        scope=scope,
        dimensions="\n".join(str(words["dimension_line"]).format(**item) for item in dimensions),
        count=_count_word(len(dimensions)),
        verdicts=_options("verdicts"), severities=_options("severities"), scenes=" / ".join(numbers),
        layout=str(words["layout"]), digest=sheet + (str(words["digest"]).format(digest=digest) if digest and not whole else ""),
        script="\n\n".join(str(episode["text"]) for episode in block),
    )
    return system, user


def _worst(table: str, keys: Sequence[str]) -> str:
    order = _keys(table)
    return max(keys, key=order.index) if keys else order[0]


def write(
    caller: LLMCaller, task: Mapping[str, Any], scenes: Sequence[Mapping[str, Any]], *, max_tokens: int, model: str = "", focus: str = "",
) -> dict[str, Any]:
    """The report, checked and merged: one call per block of episodes. ``focus`` asks for one of the focused checks instead of the full review."""
    series = len(episodes_of(task, scenes))
    episodes = reviewed(task, scenes, focus)
    if not episodes:
        raise error("no_script")
    bios = bios_of(task) if _focus(focus).get("bios") else ""
    if _focus(focus).get("bios") and not bios:
        raise ScriptReviewError(str(_data()["focus_words"]["no_bios"]))
    packed = blocks(episodes)
    if len(packed) > _limit("max_blocks"):
        raise error("too_long", blocks=len(packed), limit=_limit("max_blocks"))
    digest = submission_pack.digest(task, scenes, beats=_limit("digest_beats")) if len(packed) > 1 else ""
    dimension_keys = _dimension_keys(focus)
    severity_order = _keys("severities")
    verdicts: dict[str, list[tuple[str, str]]] = {key: [] for key in dimension_keys}
    findings: list[dict[str, Any]] = []
    strengths: list[str] = []
    summaries: list[tuple[int, int, str]] = []
    dropped = 0
    for block in packed:
        system, user = block_prompts(block, total=len(episodes), digest=digest, focus=focus, bios=bios, series=series)
        numbers = [number for episode in block for number in episode["numbers"]]
        data = call_structured(
            caller, system_prompt=system, user_prompt=user, schema=_Review, max_tokens=max_tokens,
            validators=[_validator(numbers, focus)], label="script_review", attempts=ATTEMPTS,
        ).data
        script = "\n".join(str(episode["text"]) for episode in block)
        for item in data["dimensions"]:
            verdicts[item["key"]].append((item["verdict"], _clean(item.get("note"), _limit("note_chars"))))
        for finding in data["findings"]:
            quote = _clean(finding.get("quote"), _limit("quote_chars"))
            if quote and not _in_script(quote, script):
                quote, dropped = "", dropped + 1
            findings.append({
                "dimension": finding["dimension"], "severity": finding["severity"], "scene": finding["scene"], "quote": quote,
                "issue": _clean(finding.get("issue"), _limit("issue_chars")), "fix": _clean(finding.get("fix"), _limit("fix_chars")),
            })
        strengths += [text for text in (_clean(item, _limit("strength_chars")) for item in data.get("strengths") or []) if text]
        summaries.append((int(block[0]["episode"]), int(block[-1]["episode"]), _clean(data.get("summary"), _limit("summary_chars"))))

    order = {number: index for index, number in enumerate(number for episode in episodes for number in episode["numbers"])}
    # The most serious first; within a weight, in script order, whole-script findings ahead of scene ones.
    findings.sort(key=lambda item: (-severity_order.index(item["severity"]), order.get(item["scene"], -1)))
    merged = []
    floor = _data()["verdict_floor"]
    for key in dimension_keys:
        # A verdict cannot be milder than the aspect's own worst finding.
        implied = [str(floor[item["severity"]]) for item in findings if item["dimension"] == key and item["severity"] in floor]
        worst = _worst("verdicts", [*[verdict for verdict, _note in verdicts[key]], *implied])
        note = next((note for verdict, note in verdicts[key] if verdict == worst and note), "")
        merged.append({"key": key, "verdict": worst, "note": note})
    if len(summaries) == 1:
        summary = summaries[0][2]
    else:
        summary = "\n".join(str(_data()["block_summary"]).format(first=first, last=last, text=text) for first, last, text in summaries if text)
    return {
        "version": STORE_VERSION, "focus": focus, "fingerprint": fingerprint(task, scenes, focus), "built_at": datetime.now(timezone.utc).isoformat(),
        "model": model, "calls": len(packed), "summary": summary, "dimensions": merged, "findings": findings,
        "strengths": list(dict.fromkeys(strengths))[: _limit("max_strengths")], "quotes_dropped": dropped,
    }


# --------------------------------------------------------------------------- the report as the page and the download show it


def stored(task: Mapping[str, Any], focus: str = "") -> Mapping[str, Any] | None:
    assets = task.get("assets") if isinstance(task.get("assets"), Mapping) else {}
    value = assets.get(asset_key(focus))
    return value if isinstance(value, Mapping) and value.get("version") == STORE_VERSION else None


def view(task: Mapping[str, Any], scenes: Sequence[Mapping[str, Any]], *, model: str = "", focus: str = "") -> dict[str, Any]:
    """What the page needs: the kept report with its labels (or none), whether the script changed since, and what a run costs."""
    kept = stored(task, focus)
    chosen = _focus(focus)
    report = None
    if kept:
        report = {
            "built_at": str(kept.get("built_at") or ""), "model": str(kept.get("model") or ""), "calls": int(kept.get("calls") or 0),
            "summary": str(kept.get("summary") or ""),
            "dimensions": [
                {**item, "label": _dimension_label(focus, item["key"]), "verdict_label": _label("verdicts", item["verdict"])}
                for item in kept.get("dimensions") or []
            ],
            "findings": [
                {**item, "dimension_label": _dimension_label(focus, item["dimension"]), "severity_label": _label("severities", item["severity"]),
                 "where": str(_data()["document"]["where_scene"]).format(scene=item["scene"]) if item.get("scene") else str(_data()["whole_script"])}
                for item in kept.get("findings") or []
            ],
            "strengths": list(kept.get("strengths") or []), "quotes_dropped": int(kept.get("quotes_dropped") or 0),
        }
    return {
        "title": submission_pack.title_of(task), "report": report,
        "focus": focus, "label": str(chosen["label"]), "focuses": focuses(),
        # A check held against the character sheet cannot run without one; the page says so instead of offering the button.
        "blocked": str(_data()["focus_words"]["no_bios"]) if chosen.get("bios") and not bios_of(task) else "",
        "stale": bool(kept) and kept.get("fingerprint") != fingerprint(task, scenes, focus),
        "facts": facts(task, scenes), "calls_needed": calls_needed(task, scenes, focus), "attempts": ATTEMPTS, "model": model,
        "advice": str(_data()["document"]["advice"]),
    }


def render_markdown(shown: Mapping[str, Any]) -> str:
    """The report as a Markdown document; ``shown`` is what :func:`view` returns, with a report in it."""
    words = _data()["document"]
    report = shown["report"]
    heading = (str(_data()["focus_words"]["title"]).format(title=shown["title"], label=shown["label"]) if shown.get("focus")
               else str(words["title"]).format(title=shown["title"]))
    lines = [f"# {heading}", "",
             str(words["built"]).format(time=report["built_at"], model=report["model"] or "-", calls=report["calls"]), ""]
    if shown.get("stale"):
        lines += [str(words["stale"]), ""]
    lines += [str(words["summary"]), "", report["summary"], "", str(words["dimensions"]), ""]
    lines += [str(words["dimension_row"]).format(label=item["label"], verdict=item["verdict_label"], note=item["note"]) for item in report["dimensions"]]
    lines += ["", str(words["findings"]), ""]
    if not report["findings"]:
        lines += [str(words["no_findings"]), ""]
    for index, item in enumerate(report["findings"], start=1):
        lines.append(str(words["finding"]).format(index=index, dimension=item["dimension_label"], severity=item["severity_label"], where=item["where"]))
        if item["quote"]:
            lines.append(str(words["quote"]).format(quote=item["quote"]))
        lines += [str(words["issue"]).format(issue=item["issue"]), str(words["fix"]).format(fix=item["fix"]), ""]
    if report["quotes_dropped"]:
        lines += [str(words["dropped"]).format(count=report["quotes_dropped"]), ""]
    if report["strengths"]:
        lines += [str(words["strengths"]), "", *[str(words["strength"]).format(text=text) for text in report["strengths"]], ""]
    lines += [str(words["facts"]), "", *[str(words["fact"]).format(label=item["label"], value=item["value"]) for item in shown["facts"]], "", str(words["advice"]), ""]
    return "\n".join(lines)


__all__ = [
    "ASSET_KEY", "STORE_VERSION", "ScriptReviewError", "asset_key", "bios_of", "block_prompts", "blocks", "calls_needed", "episodes_of", "error",
    "facts", "fingerprint", "focuses", "offline_text", "render_markdown", "reviewed", "stored", "view", "write",
]
