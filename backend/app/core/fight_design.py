# -*- coding: utf-8 -*-
"""Designing a fight before it is shot: why it happens, how each side fights, where it moves.

Stage 4 already turns a fight scene into shots (``DramaService._detect_scene_kind`` loads the
choreography chapters of the shot-design skill). What reaches it is only as good as the scene
the writer planned, so the writer's episode plan and visual layer get their own fight rules:

* **Cause before moves.** Who fights whom and why, how it escalates, the turn, and a win that
  comes from a weakness shown earlier, never a power that appears from nowhere.
* **A style per fighter.** Opening stance, best distance, footwork, main attack, how they
  break a guard, how they take a hit, how they finish.
* **One exchange, one chain.** Intent, wind-up and path, the other side's answer,
  hit / miss / block, the force landing, the resulting position. That end is the next exchange's start.
* **A shot is one generation, cut by its length:** 1–2 segments for 4–6 s up to 3–5 for 11–15 s,
  none shorter than 2.5 s; contact is a point on a path, and flash, shake and slow motion are rationed.
* **A route through the space,** using what the set offers, with a stable left/right relation.
* **Many against one never queues;** an ability needs its precondition set up before it fires.

The method is adapted, in this project's own words, from the Apache-2.0 ``SKILL.md`` of
qualsenWeb/fight-video-create-skill (commit 8a5afd2, reviewed 2026-10-18). Its move, ability,
scene and script libraries are CC BY-NC-ND 4.0 and shipped encrypted; none of them is used, and
its router script, which decrypts and executes a bundled payload, was not run.

A xianxia fight (flying swords, sword qi, lightning, formations) also gets the scene-level parts of
this project's own ``xianxia-combat-vfx`` reference: the three-round skeleton and the four ending
protocols in the plan, the energy states, scale kit and close exchanges in the visual layer. They are
read from that file, so it stays the single source, and the Seedance 2.5 director layer keeps reading
the same file per shot.

The fight vocabulary lives here so the writer and the storyboard stage judge a fight the same way.
"""

from __future__ import annotations

import re

from app.core import knowledge_registry, prompt_data


_WORDING_FILE = "fight_design"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/fight_design.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)

# Only fights use these words.
STRONG_SIGNALS: tuple[str, ...] = _words_of("module.strong_signals")
# Conflict words a dialogue scene uses too: they only add weight to a strong signal.
WEAK_SIGNALS: tuple[str, ...] = _words_of("module.weak_signals")
# A genre alone is no evidence (a wuxia drama has long dialogue scenes); it adds one point.
FIGHT_GENRES = frozenset({"wuxia", "xianxia", "military", "sports", "action"})
FIGHT_THRESHOLD = 3
# Words that make a fight a xianxia one (with the Seedance 2.5 director layer, which reads the same list).
XIANXIA_MARKERS: tuple[str, ...] = _words_of("module.xianxia_markers")
XIANXIA_REFERENCE = "xianxia-combat-vfx"
# Heading keywords of that reference: what the plan decides, and what each shot has to show.
XIANXIA_PLAN_SECTIONS = _words_of("module.xianxia_plan_sections")
XIANXIA_VISUAL_SECTIONS = _words_of("module.xianxia_visual_sections")


def fight_score(text: str, genre: str = "") -> int:
    """Two points per strong signal (at most three), one per weak signal or contact verb (at most two each), one for the genre.

    Without a strong signal a scene needs several distinct contact verbs (data/prompt/fight_scene.json) to count:
    a standoff full of conflict words is not a fight, a beat-by-beat exchange of blows is.
    """
    content = text or ""
    strong = sum(1 for word in STRONG_SIGNALS if word in content)
    # 不写「打斗」二字、直接写招的打戏(「挥刀劈向他的肩头，他侧身格开，反手一掌」)：接触动作够多就算。
    contact = sum(1 for word in prompt_data.words("fight_scene", "contact_verbs") if word in content)
    genre_point = 1 if str(genre or "").strip().lower() in FIGHT_GENRES else 0
    if not strong:
        return FIGHT_THRESHOLD + genre_point if contact >= prompt_data.number("fight_scene", "contact_for_fight") else 0
    weak = sum(1 for word in WEAK_SIGNALS if word in content)
    return 2 * min(strong, 3) + min(weak, 2) + min(contact, 2) + genre_point


def director_card(genre: str, text: str = "") -> str:
    """The 打法卡 section the director plan carries when the story has fighting in it, otherwise empty.

    A plan is written from a title and a few lines, so one strong signal or the genre is enough here.
    """
    content = text or ""
    if str(genre or "").strip().lower() in FIGHT_GENRES or any(word in content for word in STRONG_SIGNALS):
        return prompt_data.text("fight_scene", "director_card")
    return ""


def looks_like_fight(text: str, genre: str = "") -> bool:
    """Three points: one strong signal plus a weak one or the genre, or two strong signals."""
    return fight_score(text, genre) >= FIGHT_THRESHOLD


def is_xianxia_fight(text: str, genre: str = "") -> bool:
    """A fight whose attacks or setting are xianxia: energy, formations, immortals, demons."""
    return looks_like_fight(text, genre) and any(marker in (text or "") for marker in XIANXIA_MARKERS)


def xianxia_sections(keywords: tuple[str, ...]) -> str:
    """The ``## `` sections of the xianxia reference whose heading names one of ``keywords``.

    Lines meant for a video model's syntax (「Seedance 2.5 写法…」) stay out of the writer's prompt.
    Empty when the reference is not installed.
    """
    item = knowledge_registry.section(XIANXIA_REFERENCE)
    if item is None:
        return ""
    try:
        text = item.path.read_text(encoding="utf-8")
    except OSError:
        return ""
    picked: list[str] = []
    for block in re.split(r"(?m)^(?=## )", text):
        heading = block.splitlines()[0] if block.strip() else ""
        if heading.startswith("## ") and any(keyword in heading for keyword in keywords):
            lines = [line for line in block.splitlines() if not line.startswith("Seedance")]
            picked.append("#" + "\n".join(lines).strip())
    return "\n\n".join(picked)


PLAN_RULES = prompt_data.text("fight_scene", "plan_rules")

VISUAL_RULES = prompt_data.text("fight_scene", "visual_rules")


def _with_xianxia(rules: str, text: str, genre: str, keywords: tuple[str, ...], title: str, note: str = "") -> str:
    if not is_xianxia_fight(text, genre):
        return rules
    extra = xianxia_sections(keywords)
    lead = f"{note}\n\n" if note else ""
    return f"{rules}\n# {title}\n\n{lead}{extra}\n" if extra else rules


def plan_rules_for(*texts: str, genre: str = "") -> str:
    """The plan's fight block when this episode's text describes a fight, otherwise empty.

    A xianxia fight also gets the three-round skeleton and the four ending protocols.
    """
    text = "\n".join(str(item or "") for item in texts)
    if not looks_like_fight(text, genre):
        return ""
    from app.core import fight_exchange

    # 回合与招招写实从剧本就开始：分镜师接到的是已经按回合排好的打戏。
    rules = f"{PLAN_RULES}\n{fight_exchange.writer_rule()}\n"
    return _with_xianxia(
        rules, text, genre, XIANXIA_PLAN_SECTIONS, _text_of("plan_rules_for.text"),
        note=_text_of("plan_rules_for.note"),
    )


def visual_rules_for(*texts: str, genre: str = "") -> str:
    """The visual layer's fight block when these shots describe a fight, otherwise empty.

    A xianxia fight also gets the energy states, the scale kit and the close-exchange rules.
    """
    text = "\n".join(str(item or "") for item in texts)
    if not looks_like_fight(text, genre):
        return ""
    return _with_xianxia(VISUAL_RULES, text, genre, XIANXIA_VISUAL_SECTIONS, _text_of("visual_rules_for.text"))


__all__ = [
    "FIGHT_GENRES", "FIGHT_THRESHOLD", "PLAN_RULES", "STRONG_SIGNALS", "VISUAL_RULES", "WEAK_SIGNALS",
    "XIANXIA_MARKERS", "XIANXIA_PLAN_SECTIONS", "XIANXIA_REFERENCE", "XIANXIA_VISUAL_SECTIONS",
    "fight_score", "is_xianxia_fight", "looks_like_fight", "plan_rules_for", "visual_rules_for", "xianxia_sections",
]
