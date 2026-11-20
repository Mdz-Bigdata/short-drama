# -*- coding: utf-8 -*-
"""Why a picture or clip prompt comes out flat, read from its words.

Four checks in a fixed order; the first that finds something is the main cause:

1. does the prompt say where the camera is (shot size, height and facing, lens);
2. does the camera suit the emotion the prompt names (twelve emotions, each with a way to shoot it);
3. is there one camera move that says where it lands, or an explicit locked-off camera (clips only);
4. does it contradict itself, negate, or lean on words no model can draw.

Nothing here calls a model or changes a prompt: :func:`diagnose` returns findings, and :func:`guide`
is the text the canvas optimizer's camera mode hands to the text model so that it rewrites camera and
movement only. Tables and sentences are data (``app/data/prompt/emotion_camera.json``); the move
vocabulary and the one-move rule are the project's own (``camera_motion``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Mapping

from app.core import camera_motion, prompt_data

_DATA = "emotion_camera"
MEDIA = ("image", "video")


def _data() -> Mapping[str, Any]:
    return prompt_data.load(_DATA)


@lru_cache(maxsize=1)
def _patterns() -> dict[str, re.Pattern[str]]:
    raw = _data()["patterns"]
    keys = ("size", "angle", "lens", "anchor", "static", "end", "negation", "camera_clause", "clause_split", "negated_aside")
    return {key: re.compile(str(raw[key]), re.IGNORECASE) for key in keys}


@lru_cache(maxsize=1)
def _extra_moves() -> tuple[tuple[str, re.Pattern[str]], ...]:
    return tuple((str(name), re.compile(str(pattern), re.IGNORECASE)) for name, pattern in _data()["patterns"]["extra_moves"])


@lru_cache(maxsize=1)
def _contradictions() -> tuple[tuple[re.Pattern[str], re.Pattern[str], str], ...]:
    return tuple(
        (re.compile(str(item["first"])), re.compile(str(item["second"])), str(item["say"])) for item in _data()["contradictions"]
    )


def reset() -> None:
    """Forget the compiled tables (tests that edit the data file)."""
    _patterns.cache_clear()
    _extra_moves.cache_clear()
    _contradictions.cache_clear()
    _bare_emotion.cache_clear()


@dataclass(frozen=True)
class Finding:
    check: int
    code: str
    detail: str
    evidence: tuple[str, ...] = ()

    @property
    def title(self) -> str:
        return str(_data()["titles"][str(self.check)])

    def as_dict(self) -> dict[str, Any]:
        return {"check": self.check, "code": self.code, "title": self.title, "detail": self.detail, "evidence": list(self.evidence)}


@dataclass(frozen=True)
class Diagnosis:
    findings: tuple[Finding, ...] = ()
    emotion: str = ""
    moves: tuple[str, ...] = field(default_factory=tuple)

    @property
    def main(self) -> Finding | None:
        """The first finding of the earliest check that found anything."""
        return self.findings[0] if self.findings else None

    def as_dict(self) -> dict[str, Any]:
        return {
            "findings": [item.as_dict() for item in self.findings],
            "main": self.main.code if self.main else "",
            "emotion": self.emotion, "moves": list(self.moves),
        }


def _say(key: str, /, **values: object) -> str:
    return str(_data()["findings"][key]).format(**values)


def _found(pattern: re.Pattern[str], text: str) -> list[str]:
    cap = int(_data()["limits"]["evidence_items"])
    return list(dict.fromkeys(match.group(0) for match in pattern.finditer(text)))[:cap]


def emotions() -> list[dict[str, Any]]:
    """The twelve emotions with the way each is shot, for a page or a prompt."""
    names = [str(name) for name in _data()["dimensions"]]
    return [
        {
            "id": str(row["id"]), "label": str(row["label"]), "why": str(row["why"]), "avoid": str(row["avoid"]),
            "recipe": [{"dimension": name, "take": str(take)} for name, take in zip(names, row["recipe"])],
        }
        for row in _data()["emotions"]
    ]


def emotion_in(text: str) -> Mapping[str, Any] | None:
    """The emotion a prompt names: the one with the most cue words, the earliest on a tie."""
    best: tuple[int, int, Mapping[str, Any]] | None = None
    for row in _data()["emotions"]:
        places = [text.find(str(cue)) for cue in row["cues"]]
        hits = [place for place in places if place >= 0]
        if not hits:
            continue
        rank = (-len(hits), min(hits), row)
        if best is None or rank[:2] < best[:2]:
            best = rank
    return best[2] if best else None


def _recipe(row: Mapping[str, Any]) -> str:
    return str(_data()["limits"]["recipe_joiner"]).join(str(item) for item in row["recipe"])


def camera_words(text: str) -> str:
    """The clauses of a prompt that are about the camera.

    A whole prompt also says what people and things do (「热气升起」「她拉开窗帘」); only a clause that
    names the camera or uses a word nothing but a camera does is read for moves.
    """
    patterns = _patterns()
    clauses = [clause for clause in patterns["clause_split"].split(text) if patterns["camera_clause"].search(clause)]
    # 「不推不拉、无变焦」 rules moves out; what is ruled out is not a move the prompt asks for.
    return patterns["negated_aside"].sub("", "，".join(clauses))


def moves_in(text: str) -> list[str]:
    """The kinds of camera move a prompt asks for, in the project's own classes plus zooms and whips."""
    text = camera_words(text)
    found = list(camera_motion.move_classes(text))
    for name, pattern in _extra_moves():
        if pattern.search(text) and name not in found:
            found.append(name)
    # A dolly zoom is one move, not a zoom on top of a push.
    if "推轨变焦" in found and "变焦" in found:
        found.remove("变焦")
    return found


def diagnose(text: str, medium: str = "video") -> Diagnosis:
    """What the four checks find in ``text``; an empty diagnosis when the prompt says all it should."""
    text = str(text or "")[: int(_data()["limits"]["text_chars"])]
    if not text.strip():
        return Diagnosis()
    patterns = _patterns()
    findings: list[Finding] = []
    sizes, angles = _found(patterns["size"], text), _found(patterns["angle"], text)
    anchored = bool(patterns["anchor"].search(text))

    # ① where is the camera
    if not sizes and not angles and not anchored:
        findings.append(Finding(1, "no_camera", _say("no_camera")))
    else:
        if not sizes:
            findings.append(Finding(1, "no_size", _say("no_size")))
        if not angles and not anchored:
            findings.append(Finding(1, "no_angle", _say("no_angle")))

    # ② does it suit the emotion
    row = emotion_in(text)
    moves = moves_in(text) if medium == "video" else []
    if row is not None:
        clashing = [word for word in row["clash_sizes"] if word in sizes]
        # 「特写」 inside 「大特写」/「中特写」 is one word, already matched whole by the size pattern.
        clashing += [word for word in row["clash_angles"] if word in angles]
        clashing += [word for word in row["clash_moves"] if word in moves]
        if clashing:
            findings.append(Finding(
                2, "emotion_clash",
                _say("emotion_clash", emotion=row["label"], words="、".join(clashing), avoid=row["avoid"], recipe=_recipe(row)),
                tuple(clashing),
            ))
        elif not sizes and not angles and not anchored:
            findings.append(Finding(2, "emotion_only", _say("emotion_only", emotion=row["label"], recipe=_recipe(row))))

    # ③ one move that lands somewhere (a still has no move to check)
    if medium == "video":
        problem = camera_motion.motion_problem(camera_words(text))
        if problem:
            findings.append(Finding(3, "move_problem", _say("move_problem", problem=problem), tuple(moves)))
        for pair in _data()["risky_pairs"]:
            if all(move in moves for move in pair["moves"]):
                findings.append(Finding(3, "risky_pair", _say("risky_pair", pair=pair["say"]), tuple(pair["moves"])))
                break
        static = bool(patterns["static"].search(text))
        travelling = [move for move in moves if move != "手持"]
        if travelling and not patterns["end"].search(text):
            findings.append(Finding(3, "no_end", _say("no_end", moves="、".join(travelling)), tuple(travelling)))
        elif not moves and not static:
            findings.append(Finding(3, "unstated", _say("unstated")))

    # ④ contradictions, negations, words nothing can draw
    for first, second, say in _contradictions():
        one, two = first.search(text), second.search(text)
        if one and two:
            findings.append(Finding(4, "contradiction", _say("contradiction", say=say), (one.group(0), two.group(0))))
    negations = _found(patterns["negation"], text)
    if negations:
        findings.append(Finding(4, "negation", _say("negation", words="、".join(negations)), tuple(negations)))
    vague = [word for word in _data()["vague_words"] if str(word) in text][: int(_data()["limits"]["evidence_items"])]
    if vague:
        findings.append(Finding(4, "vague", _say("vague", words="、".join(vague)), tuple(vague)))

    findings.sort(key=lambda item: item.check)
    return Diagnosis(findings=tuple(findings), emotion=str(row["label"]) if row is not None else "", moves=tuple(moves))


def guide() -> str:
    """The method and the emotion table the text model rewrites by."""
    words = _data()["guide"]
    lines = [str(words["head"]), "", str(words["table_head"])]
    lines += [str(words["row"]).format(label=row["label"], recipe=_recipe(row), avoid=row["avoid"]) for row in _data()["emotions"]]
    lines += ["", str(words["turns_head"])]
    lines += [str(words["turn"]).format(name=turn["name"], how=turn["how"]) for turn in _data()["turns"]]
    return "\n".join(lines)


def findings_block(diagnosis: Diagnosis) -> str:
    """The rule check's findings as the lines that go under the prompt in the user message."""
    words = _data()["guide"]
    if not diagnosis.findings:
        return str(words["found_none"]) + "\n"
    lines = [str(words["found_head"])]
    lines += [str(words["found_line"]).format(title=item.title, detail=item.detail) for item in diagnosis.findings]
    return "\n".join(lines) + "\n"


@lru_cache(maxsize=1)
def _bare_emotion() -> re.Pattern[str]:
    rules = _data()["bare_emotion"]
    words = "|".join(sorted((re.escape(str(word)) for word in rules["words"]), key=len, reverse=True))
    marks = re.escape(str(rules["separators"]))
    return re.compile(
        rf"(?P<lead>^|[{marks}])[ \t]*{rules['prefix']}(?P<word>{words}){rules['suffix']}[ \t]*(?P<trail>[{marks}]|$)"
    )


def without_bare_emotions(text: str) -> tuple[str, list[str]]:
    """``text`` without the emotion words that stand as a clause of their own, and the words taken out.

    「…固定机位。孤独。」 loses the last clause; 「她孤独地坐着」 is a description and stays. The camera
    carries the emotion; a bare label only invites the model to paint the feeling onto a face.
    """
    removed: list[str] = []

    def drop(match: re.Match[str]) -> str:
        removed.append(match.group("word"))
        lead, trail = match.group("lead"), match.group("trail")
        # The clause goes, and with it one of the two marks that fenced it; a line break is never lost.
        if not lead or not trail:
            return "\n" if "\n" in (lead, trail) and lead and trail else ""
        if lead == "\n":
            return "\n"
        return lead + "\n" if trail == "\n" else trail

    cleaned = str(text or "")
    for _ in range(8):
        shorter = _bare_emotion().sub(drop, cleaned)
        if shorter == cleaned:
            break
        cleaned = shorter
    return (cleaned.strip(), list(dict.fromkeys(removed))) if removed else (str(text or ""), [])


def bare_emotion_change(words: list[str]) -> str:
    """The line that tells the creator which bare emotion words were taken out, and why."""
    return str(_data()["bare_emotion"]["change"]).format(words="、".join(words))


def reference() -> dict[str, Any]:
    """Everything a page shows next to the diagnosis: the principle, the table, how a scene turns, beat patterns."""
    data = _data()
    return {
        "principle": str(data["principle"]),
        "emotions": emotions(),
        "turns": [{"name": str(item["name"]), "how": str(item["how"])} for item in data["turns"]],
        "beats": [{"name": str(item["name"]), "shots": str(item["shots"])} for item in data["beats"]],
        "beat_rule": str(data["beat_rule"]),
    }


__all__ = ["Diagnosis", "Finding", "MEDIA", "bare_emotion_change", "camera_words", "diagnose", "emotion_in", "emotions", "findings_block", "guide", "moves_in", "reference", "reset", "without_bare_emotions"]
