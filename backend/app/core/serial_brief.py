# -*- coding: utf-8 -*-
"""What a creator fixes about a serial before it is planned: genres, tone, ending, and whether it goes overseas.

A serial can name up to three genres (the first sets the key, the others flavour it), one tone, one
kind of ending, and an overseas switch. Each choice is optional; what was chosen is told to the stage-1
director as a short brief (who watches this genre and what they wait for, a way to open, which payoffs
and episode-end hooks to lean on, how the opposition is layered, how the tone and the ending are
written), and the episode planner gets one line per batch plus the ending rule on the batch that
reaches the last episode. Nothing chosen means nothing is added: the prompts stay as they were.

Only serials get this (creation types ``drama`` and ``narration``), and not a project whose script was
uploaded. Nothing here is checked afterwards or sent back. Tables and sentences are data
(``app/data/prompt/serial_brief.json``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.core import prompt_data

_DATA = "serial_brief"
GENRES_KEY = "story_genres"
TONE_KEY = "story_tone"
ENDING_KEY = "ending_type"
OVERSEAS_KEY = "overseas"
SERIAL_MODES = frozenset({"drama", "narration"})


def _data() -> Mapping[str, Any]:
    return prompt_data.load(_DATA)


def _genres() -> dict[str, Mapping[str, Any]]:
    return {str(row["id"]): row for row in _data()["genres"]}


def max_genres() -> int:
    return int(_data()["limits"]["max_genres"])


def normalize_genres(raw: Any) -> list[str]:
    """Known genre ids in the order given, without repeats, at most the limit; the first one leads."""
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return []
    known = _genres()
    return list(dict.fromkeys(str(item).strip() for item in raw if str(item).strip() in known))[: max_genres()]


def _choice(table: str, raw: Any) -> str:
    value = str(raw or "").strip()
    return value if value in _data()[table] else ""


def normalize_tone(raw: Any) -> str:
    return _choice("tones", raw)


def normalize_ending(raw: Any) -> str:
    return _choice("endings", raw)


def applies(config: Mapping[str, Any] | None) -> bool:
    data = config or {}
    mode = str(data.get("creation_mode") or "drama").strip() or "drama"
    return mode in SERIAL_MODES and not data.get("script_content")


def of(config: Mapping[str, Any] | None) -> dict[str, Any]:
    """The brief as stored: ``{story_genres, story_tone, ending_type, overseas}``, empty values when not chosen."""
    data = config or {}
    if not applies(data):
        return {GENRES_KEY: [], TONE_KEY: "", ENDING_KEY: "", OVERSEAS_KEY: False}
    return {
        GENRES_KEY: normalize_genres(data.get(GENRES_KEY)), TONE_KEY: normalize_tone(data.get(TONE_KEY)),
        ENDING_KEY: normalize_ending(data.get(ENDING_KEY)), OVERSEAS_KEY: bool(data.get(OVERSEAS_KEY)),
    }


def chosen(config: Mapping[str, Any] | None) -> bool:
    brief = of(config)
    return bool(brief[GENRES_KEY] or brief[TONE_KEY] or brief[ENDING_KEY] or brief[OVERSEAS_KEY])


def lead_genre(config: Mapping[str, Any] | None) -> str:
    """The genre that sets the key, or ``""``; the paywall plan reads its strongest cliff from it."""
    picked = of(config)[GENRES_KEY]
    return picked[0] if picked else ""


def paywall_kind(genre: str) -> str:
    """The paywall cliff a genre's audience waits for most; ``""`` for an unknown genre."""
    return str(_genres().get(genre, {}).get("paywall") or "")


def clashes(genres: list[str]) -> list[str]:
    picked = set(genres)
    return [str(row["say"]) for row in _data()["clashes"] if set(row["pair"]) <= picked]


def catalog() -> dict[str, Any]:
    """Everything the new-project form shows: genres, tones, endings, the overseas switch, the limit."""
    data = _data()
    return {
        "max_genres": max_genres(),
        "genres": [{"id": str(row["id"]), "label": str(row["label"]), "hint": str(row["hint"]), "audience": str(row["audience"]),
                    "payoff": str(row["payoff"])} for row in data["genres"]],
        "clashes": [{"pair": [str(item) for item in row["pair"]], "say": str(row["say"])} for row in data["clashes"]],
        "tones": [{"id": key, "label": str(row["label"]), "hint": str(row["hint"])} for key, row in data["tones"].items()],
        "endings": [{"id": key, "label": str(row["label"]), "hint": str(row["hint"])} for key, row in data["endings"].items()],
        "overseas": {"label": str(data["overseas"]["label"]), "hint": str(data["overseas"]["hint"])},
    }


def director_rule(config: Mapping[str, Any] | None) -> str:
    """The brief for the stage-1 director; empty when nothing was chosen or the project is not a serial."""
    if not chosen(config):
        return ""
    data = _data()
    says = data["director"]
    joiner = str(data["joiner"])
    brief = of(config)
    lines = [str(says["head"])]
    genres = [_genres()[key] for key in brief[GENRES_KEY]]
    if genres:
        labels = str(data["chain_joiner"]).join(str(row["label"]) for row in genres)
        lines.append(str(says["genres_one"]).format(labels=labels) if len(genres) == 1
                     else str(says["genres_many"]).format(labels=labels, lead=genres[0]["label"]))
        lines += [str(says["genre_line"]).format(label=row["label"], hint=row["hint"], audience=row["audience"], payoff=row["payoff"])
                  for row in genres]
        lines += [str(says["clash"]).format(say=say) for say in clashes(brief[GENRES_KEY])]
        lead = genres[0]
        opening = data["openings"][str(lead["opening"])]
        lines.append(str(says["opening"]).format(label=opening["label"], how=opening["how"]))
        main, second = (str(data["payoffs"][key]) for key in lead["payoffs"][:2])
        lines.append(str(says["payoffs"]).format(main=main, second=second))
        lines.append(str(says["hooks"]).format(names=joiner.join(str(data["hooks"][key]) for key in lead["hooks"])))
        lines.append(str(says["villains"]).format(chain=lead["villains"]) + str(data["villain_tiers"]))
    if brief[TONE_KEY]:
        tone = data["tones"][brief[TONE_KEY]]
        lines.append(str(says["tone"]).format(label=tone["label"], rule=tone["rule"]))
    if brief[ENDING_KEY]:
        ending = data["endings"][brief[ENDING_KEY]]
        lines.append(str(says["ending"]).format(label=ending["label"], rule=ending["rule"]))
    if brief[OVERSEAS_KEY]:
        lines.append(str(data["overseas"]["rule"]))
    return "\n".join(lines)


def outline_rules(creation: Mapping[str, Any] | None, *, last: int = 0, total: int = 0) -> list[str]:
    """One line for a batch of the episode planner, plus the ending rule on the batch that reaches the last episode."""
    if not chosen(creation):
        return []
    data = _data()
    says = data["outline"]
    brief = of(creation)
    parts: list[str] = []
    if brief[GENRES_KEY]:
        labels = str(data["chain_joiner"]).join(str(_genres()[key]["label"]) for key in brief[GENRES_KEY])
        parts.append(str(says["genres"]).format(labels=labels))
    if brief[TONE_KEY]:
        tone = data["tones"][brief[TONE_KEY]]
        parts.append(str(says["tone"]).format(label=tone["label"], rule=str(tone["rule"]).rstrip("。")))
    if brief[ENDING_KEY]:
        parts.append(str(says["ending"]).format(label=data["endings"][brief[ENDING_KEY]]["label"]))
    if brief[OVERSEAS_KEY]:
        parts.append(str(says["overseas"]))
    rules = [str(says["line"]).format(parts=str(says["joiner"]).join(parts))]
    if brief[ENDING_KEY] and total and last >= total:
        rules.append(str(says["last_batch"]).format(rule=data["endings"][brief[ENDING_KEY]]["rule"]))
    return rules


__all__ = [
    "ENDING_KEY", "GENRES_KEY", "OVERSEAS_KEY", "TONE_KEY", "applies", "catalog", "chosen", "clashes", "director_rule",
    "lead_genre", "max_genres", "normalize_ending", "normalize_genres", "normalize_tone", "of", "outline_rules", "paywall_kind",
]
