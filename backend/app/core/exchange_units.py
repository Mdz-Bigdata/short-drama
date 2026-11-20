# -*- coding: utf-8 -*-
"""Exchange units: how many beats a shot holds, by who is moving and how they talk.

Two masters nine seconds into a fight should have traded four blows, not two; a ten-second
dialogue shot should hold a full exchange, not half of one followed by a sigh. The producer's
1023–1025 packs (vendored as the ``exchange-unit-master`` skill) fix the grain:

* **Fights are catch → turn → strike.** One *half-unit* is one fighter receiving the incoming
  blow, turning it aside and sending a new one; that strike is the next half-unit's incoming
  blow. U1 = the opening plus the other side's first answer, every later U adds one half-unit.
  A half-unit lasts the style's tempo (MS1 trapping 0.75 s … MS6 tai chi 2.5 s) times the
  fighters' interaction power (IP7 masters ×0.85 … IP2 the frail ×2; the gravely ill do not
  trade blows), ×1.2 with three or more fighters, never under 0.6 s.
* **Dialogue is listen → think → answer.** A turn lasts the scene's dialogue tempo (DT1 a row
  4 s … DT5 a farewell 9 s) and holds (turn − think) × rate × 0.85 characters. Two people
  talking get at least two turns a shot, the last line lands within the tail margin of the end,
  and three or more turns arc through 起承转合.

Everything is read from the skill's tables through the knowledge registry, so the CSVs stay the
single source; when the skill is not installed the planner returns nothing and checks nothing.
``scene_plan`` judges a scene, ``ScenePlan.brief`` is what the stage-4 table writer reads, and
``audit_shot`` is what the shot-table audit checks the table against.
"""

from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterable, Sequence

from app.core import knowledge_registry
from app.core import prompt_data


_WORDING_FILE = "exchange_units"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/exchange_units.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)

CODE_TABLE = "exchange-unit-code-table"
SPEC = "exchange-unit-spec"
MARTIAL_TEMPO = "exchange-martial-tempo"
DIALOGUE_TEMPO = "exchange-dialogue-tempo"

DEFAULT_STYLE = "MS3"        # P11-53: modern, street, police and ring fights default to sanda.
DEFAULT_DIALOGUE = "DT3"
DEFAULT_POWER = "IP3"
MARTIAL_TAIL = 1.5           # chain rule 7: the last U lands within 1.5 s of the shot's end
FIGHT_LINE_CHARS = 8         # P12-12: a line inside a fight is at most eight characters
LINE_BUDGET_FACTOR = 0.85    # P12-11
LINE_BUDGET_SLACK = 1.3      # SI-75 flags a turn over 1.3 × its budget
ONE_SIDED_GAP = 3            # MX2: three tiers apart, the stronger side sets the pace
PREVIEW_SECONDS = (8, 10, 12, 15)

# Words that hold a weapon's character without being a weapon (「剑眉星目」 is a face).
_NOT_WEAPONS = _words_of("module.not_weapons")
# State adjustments of the code table (力量状态修正) that we can read off a character's own text.
_STATE_DROPS = ((_text_of("module.state_drops"), 2), (_text_of("module.state_drops.2"), 2), (_text_of("module.state_drops.3"), 1), (_text_of("module.state_drops.4"), 1), (_text_of("module.state_drops.5"), 1), (_text_of("module.state_drops.6"), 1), (_text_of("module.state_drops.7"), 1))
_SIGHS = _words_of("module.sighs")
_U_LABEL = re.compile(_text_of("module.u_label"))
_BRACED = re.compile(r"[{｛]([^{}｛｝]+)[}｝]")
_NOTE = re.compile(r"[（(][^）)]*(?:[）)]|$)")
_QUOTES = re.compile(r"[「」『』“”\"'‘’\s]")
_STROKES = re.compile(_text_of("module.strokes"))


@dataclass(frozen=True)
class MartialTempo:
    code: str
    name: str
    half: float
    low: float
    high: float
    phrase: tuple[int, int]
    pause: float
    opening: float
    traits: str
    words: tuple[str, ...]


@dataclass(frozen=True)
class PowerTier:
    code: str
    name: str
    who: str
    words: tuple[str, ...]
    craft: str
    calm_unit: float          # T2 常态: one interaction unit outside a fight, in seconds

    @property
    def rank(self) -> int:
        return int(self.code[2:])


@dataclass(frozen=True)
class DialogueTempo:
    code: str
    name: str
    turn: float
    low: float
    high: float
    think: float
    rate: float
    tail: float
    words: tuple[str, ...]

    def budget(self, seconds: float | None = None) -> int:
        """How many characters one turn holds: (turn − think) × rate × 0.85."""
        length = self.turn if seconds is None else seconds
        return max(1, round((length - self.think) * self.rate * LINE_BUDGET_FACTOR))


@dataclass(frozen=True)
class Tables:
    styles: dict[str, MartialTempo]
    powers: dict[str, PowerTier]
    dialogue: dict[str, DialogueTempo]
    multipliers: dict[str, float]
    crowd: float
    min_half: float


def _rows(key: str) -> list[list[str]]:
    item = knowledge_registry.section(key)
    if item is None:
        return []
    try:
        with item.path.open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.reader(handle))
    except OSError:
        return []


def _numbers(text: str) -> list[float]:
    return [float(value) for value in re.findall(r"\d+(?:\.\d+)?", text)]


def _words(text: str) -> tuple[str, ...]:
    return tuple(word for word in re.split(r"[\s｜|、]+", text) if word)


@lru_cache(maxsize=1)
def tables() -> Tables | None:
    """The skill's tables, parsed once; ``None`` when the skill is not installed."""
    martial = _rows(MARTIAL_TEMPO)
    dialogue = _rows(DIALOGUE_TEMPO)
    code = _rows(CODE_TABLE)
    spec = knowledge_registry.section(SPEC)
    if not (martial and dialogue and code and spec):
        return None
    styles: dict[str, MartialTempo] = {}
    for row in martial[1:]:
        if len(row) < 10:
            continue
        phrase = [int(value) for value in _numbers(row[5])] or [3, 5]
        styles[row[0]] = MartialTempo(
            code=row[0], name=row[1], half=float(row[2]), low=float(row[3]), high=float(row[4]),
            phrase=(phrase[0], phrase[-1]), pause=float(row[6]), opening=float(row[7]),
            traits=row[8], words=_words(row[9]),
        )
    powers: dict[str, PowerTier] = {}
    for row in code[1:]:
        if len(row) < 6 or row[0] != _text_of("tables.text"):
            continue
        judged, _, craft = row[5].partition(_text_of("tables.text.2"))
        words = _words(judged.split(_text_of("tables.words"), 1)[1]) if _text_of("tables.words.2") in judged else ()
        calm = re.search(r"T2\s*(\d+(?:\.\d+)?)", row[3])
        powers[row[1]] = PowerTier(
            code=row[1], name=row[2], who=row[4], words=words, craft=craft.strip(),
            calm_unit=float(calm.group(1)) if calm else 4.0,
        )
    tempos: dict[str, DialogueTempo] = {}
    for row in dialogue[1:]:
        if len(row) < 10:
            continue
        tempos[row[0]] = DialogueTempo(
            code=row[0], name=row[1], turn=float(row[3]), low=float(row[4]), high=float(row[5]),
            think=float(row[6]), rate=float(row[7]), tail=float(row[8]), words=_words(row[9]),
        )
    try:
        text = spec.path.read_text(encoding="utf-8")
    except OSError:
        return None
    line = next((item for item in text.splitlines() if item.startswith(_text_of("tables.line"))), "")
    multipliers = {f"IP{tier}": float(value) for tier, value in re.findall(r"IP(\d)\s*×\s*(\d+(?:\.\d+)?)", line)}
    crowd = re.search(_text_of("tables.crowd"), line)
    floor = re.search(_text_of("tables.floor"), line)
    if not (styles and powers and tempos and multipliers):
        return None
    return Tables(
        styles=styles, powers=powers, dialogue=tempos, multipliers=multipliers,
        crowd=float(crowd.group(1)) if crowd else 1.2, min_half=float(floor.group(1)) if floor else 0.6,
    )


def _best(text: str, candidates: Iterable[tuple[str, tuple[str, ...]]]) -> str:
    """The candidate with the most words in ``text`` (first wins a tie); empty when none hits."""
    scored = [(sum(text.count(word) for word in words), code) for code, words in candidates]
    best = max(scored, default=(0, ""), key=lambda item: item[0])
    return best[1] if best[0] else ""


def judge_style(text: str) -> str:
    """The martial tempo tier the text names (MS1–MS10), or empty when it names none."""
    data = tables()
    if data is None:
        return ""
    content = str(text or "")
    for phrase in _NOT_WEAPONS:
        content = content.replace(phrase, "")
    return _best(content, ((item.code, item.words) for item in data.styles.values()))


def judge_dialogue(text: str) -> str:
    """The dialogue tempo the text names (DT1–DT6), or empty when it names none."""
    data = tables()
    if data is None:
        return ""
    return _best(str(text or ""), ((item.code, item.words) for item in data.dialogue.values()))


def judge_power(text: str) -> str:
    """One person's interaction power: health over skill over age, then state drops (IP1–IP7).

    Empty when the text gives no clue at all — the caller decides the default.
    """
    data = tables()
    if data is None:
        return ""
    content = str(text or "")

    def hit(code: str) -> bool:
        return code in data.powers and any(word in content for word in data.powers[code].words)

    if hit("IP1"):
        return "IP1"
    skilled = next((code for code in ("IP7", "IP6", "IP5") if hit(code)), "")
    if skilled:
        drop = max(
            (steps for word, steps in _STATE_DROPS
             if word in content and not (word.startswith(_text_of("judge_power.drop")) and _text_of("judge_power.drop.2") in content)),
            default=0,
        )
        return f"IP{max(3, int(skilled[2:]) - drop)}"
    return next((code for code in ("IP2", "IP4") if hit(code)), "")


@dataclass
class FightTempo:
    style: str
    style_named: bool
    powers: dict[str, str]
    multiplier: float
    rule: str                 # how the fighters' tiers were combined
    crowd: bool
    half: float
    low: float
    high: float
    tempo: MartialTempo

    def halves_for(self, seconds: float) -> int:
        """Half-units a shot of ``seconds`` holds: opening, phrases with breaks, the tail kept short."""
        tempo = self.tempo
        size = max(1, (tempo.phrase[0] + tempo.phrase[1]) // 2)
        clock, count, in_phrase = tempo.opening, 0, 0
        while clock + self.half <= seconds + 1e-9:
            clock += self.half
            count += 1
            in_phrase += 1
            # A break only where another half-unit still fits after it (a break is never filler at the end).
            if in_phrase >= size and tempo.pause and clock + tempo.pause + self.half <= seconds + 1e-9:
                clock += tempo.pause
                in_phrase = 0
        return count


@dataclass
class ScenePlan:
    fight: FightTempo | None = None
    dialogue: DialogueTempo | None = None
    dialogue_named: bool = False
    powers: dict[str, str] = field(default_factory=dict)
    calm_unit: float | None = None
    notes: list[str] = field(default_factory=list)

    def brief(self) -> str:
        """The stage-4 table writer's 「单元环扣」 block for this scene."""
        data = tables()
        if data is None:
            return ""
        lines = list(_words_of("brief.lines"))
        if self.powers:
            described = "、".join(
                f"{name} {code} {data.powers[code].name}" for name, code in self.powers.items() if code in data.powers
            )
            if described:
                lines.append(_text_of("brief.text").format(described))
        if self.fight is not None:
            lines.extend(self._fight_lines(data))
        elif self.calm_unit is not None:
            crafts = "；".join(
                f"{data.powers[code].name}：{data.powers[code].craft}"
                for code in dict.fromkeys(self.powers.values()) if code in data.powers and data.powers[code].craft
            )
            lines.append(
                _text_of("brief.text.2").format(self.calm_unit)
                + (f"；{crafts}" if crafts else "") + "。"
            )
        if self.dialogue is not None:
            lines.extend(self._dialogue_lines())
        lines.extend(f"- {note}" for note in self.notes)
        return "\n".join(lines) if len(lines) > 1 else ""

    def _fight_lines(self, data: Tables) -> list[str]:
        fight = self.fight
        assert fight is not None
        tempo = fight.tempo
        style = f"{tempo.code} {tempo.name}" + ("" if fight.style_named else _text_of("_fight_lines.style"))
        counts = "、".join(
            _text_of("_fight_lines.counts").format(seconds, fight.halves_for(seconds)) for seconds in PREVIEW_SECONDS
        )
        crowd = _text_of("_fight_lines.crowd").format(data.crowd) if fight.crowd else ""
        pause = (
            _text_of("_fight_lines.pause").format(tempo.pause) if tempo.pause
            else _text_of("_fight_lines.pause.2")
        )
        return [
            _text_of("_fight_lines.text").format(style, fight.rule, fight.multiplier, crowd, fight.half, fight.low, fight.high, tempo.opening, tempo.phrase[0], tempo.phrase[1], pause, tempo.traits),
            _text_of("_fight_lines.text.2").format(counts),
            _text_of("_fight_lines.text.3"),
        ]

    def _dialogue_lines(self) -> list[str]:
        tempo = self.dialogue
        assert tempo is not None
        named = "" if self.dialogue_named else _text_of("_dialogue_lines.named")
        fight = _text_of("_dialogue_lines.fight").format(FIGHT_LINE_CHARS) if self.fight else ""
        return [
            _text_of("_dialogue_lines.text").format(tempo.code, tempo.name, named, tempo.turn, tempo.low, tempo.high, tempo.think, tempo.rate, tempo.budget()),
            _text_of("_dialogue_lines.text.2").format(tempo.tail, fight),
            _text_of("_dialogue_lines.text.3"),
        ]


def _combine(data: Tables, powers: dict[str, str]) -> tuple[float, str]:
    """The pair's multiplier: one-sided → the stronger side's; otherwise the average (MX1/MX2)."""
    fighters = [code for code in powers.values() if code != "IP1" and code in data.multipliers]
    if not fighters:
        return data.multipliers.get(DEFAULT_POWER, 1.5), _text_of("_combine.text")
    ranks = sorted({int(code[2:]) for code in fighters})
    if len(ranks) == 1:
        code = f"IP{ranks[0]}"
        return data.multipliers[code], _text_of("_combine.text.2").format(code, data.powers[code].name)
    strongest = f"IP{ranks[-1]}"
    if ranks[-1] - ranks[0] >= ONE_SIDED_GAP:
        return data.multipliers[strongest], _text_of("_combine.text.3").format(strongest)
    average = sum(data.multipliers[code] for code in fighters) / len(fighters)
    return round(average, 3), _text_of("_combine.text.4")


_QUOTED = re.compile(r"[「“\"][^」”\"]{2,}[」”\"]")


def has_lines(text: str, cast: Sequence[str] = ()) -> bool:
    """Whether the scene has spoken lines: a named speaker label, a 【name】 line, or quoted speech."""
    content = str(text or "")
    if _QUOTED.search(content) or re.search(r"(?m)^\s*【[^】]{1,12}】", content):
        return True
    return bool(_labels(content, cast)) if cast else bool(re.search(_text_of("has_lines.text"), content))


def scene_plan(
    text: str,
    *,
    profiles: dict[str, str] | None = None,
    fight: bool = False,
    has_dialogue: bool | None = None,
) -> ScenePlan | None:
    """Judge one scene: its fighters' power, its style and dialogue tempo. ``None`` without the skill.

    ``profiles`` maps each character in the scene to their description; power is judged per person
    from it. Without profiles the scene text as a whole is judged once.
    """
    data = tables()
    if data is None:
        return None
    content = str(text or "")
    people = {name: desc for name, desc in (profiles or {}).items() if str(name).strip()}
    powers = {name: judge_power(desc) for name, desc in people.items()}
    powers = {name: code for name, code in powers.items() if code}
    if not people:
        scene_power = judge_power(content)
        if scene_power:
            powers = {_text_of("scene_plan.powers"): scene_power}
    plan = ScenePlan(powers=powers)

    if fight:
        frail = [name for name, code in powers.items() if code == "IP1"]
        if frail:
            plan.notes.append(_text_of("scene_plan.text").format('、'.join(frail)))
        style = judge_style(content)
        tempo = data.styles.get(style or DEFAULT_STYLE) or next(iter(data.styles.values()))
        multiplier, rule = _combine(data, powers)
        crowd = len([code for code in powers.values() if code != "IP1"]) >= 3 or len(people) >= 3
        factor = multiplier * (data.crowd if crowd else 1.0)
        plan.fight = FightTempo(
            style=tempo.code, style_named=bool(style), powers=powers, multiplier=multiplier, rule=rule, crowd=crowd,
            half=max(data.min_half, tempo.half * factor), low=max(data.min_half, tempo.low * factor),
            high=max(data.min_half, tempo.high * factor), tempo=tempo,
        )
    elif powers:
        # Outside a fight the slower person sets the pace (MX3): a child helping a grandmother moves at her speed.
        slowest = min((data.powers[code] for code in powers.values() if code in data.powers), key=lambda tier: tier.rank)
        plan.calm_unit = slowest.calm_unit

    talks = has_dialogue if has_dialogue is not None else has_lines(content, list(people))
    if talks:
        named = judge_dialogue(content)
        plan.dialogue = data.dialogue.get(named or DEFAULT_DIALOGUE)
        plan.dialogue_named = bool(named)
    return plan


@dataclass(frozen=True)
class Turn:
    speaker: str
    text: str

    @property
    def chars(self) -> int:
        return len(_STROKES.findall(self.text))


def _spoken(segment: str) -> str:
    """What is said aloud: the braced text when there is any, without 语气 notes and quotes."""
    braced = _BRACED.findall(segment)
    text = "".join(braced) if braced else segment
    return _QUOTES.sub("", _NOTE.sub("", text)).strip("；;，, ")


def split_turns(dialogue: str, cast: Sequence[str]) -> list[Turn]:
    """The dialogue cell as turns: consecutive lines of one speaker are one turn.

    Only labels that name someone in ``cast`` start a turn, so 「他说：走」 stays inside a line.
    """
    names = sorted({str(name).strip() for name in cast if str(name).strip()}, key=len, reverse=True)
    text = str(dialogue or "")
    if not names or not text.strip():
        return []
    label = re.compile("(" + "|".join(re.escape(name) for name in names) + r")(?:[（(][^）)]*[）)])?\s*[：:]")
    marks = list(label.finditer(text))
    turns: list[Turn] = []
    for index, mark in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        spoken = _spoken(text[mark.end():end])
        if not spoken:
            continue
        if turns and turns[-1].speaker == mark.group(1):
            turns[-1] = Turn(mark.group(1), turns[-1].text + spoken)
        else:
            turns.append(Turn(mark.group(1), spoken))
    return turns


def _labels(dialogue: str, cast: Sequence[str]) -> list[str]:
    names = sorted({str(name).strip() for name in cast if str(name).strip()}, key=len, reverse=True)
    if not names:
        return []
    pattern = re.compile("(" + "|".join(re.escape(name) for name in names) + r")(?:[（(][^）)]*[）)])?\s*[：:]")
    return [match.group(1) for match in pattern.finditer(str(dialogue or ""))]


def count_units(desc: str) -> int:
    """How many U the description writes; 「U3–U4」 counts two."""
    numbers: set[int] = set()
    for match in _U_LABEL.finditer(str(desc or "")):
        first = int(match.group(1))
        last = int(match.group(2)) if match.group(2) else first
        numbers.update(range(min(first, last), max(first, last) + 1))
    return len(numbers)


@dataclass(frozen=True)
class UnitIssue:
    rule: str
    detail: str


def audit_shot(
    plan: ScenePlan | None,
    *,
    seconds: float,
    characters: Sequence[str],
    dialogue: str,
    desc: str,
    fight_shot: bool,
) -> list[UnitIssue]:
    """The pack's hard checks on one shot of the table (SI-69, 70, 72, 75 and the chain rules)."""
    if plan is None:
        return []
    issues: list[UnitIssue] = []
    turns = split_turns(dialogue, characters)
    labels = _labels(dialogue, characters)
    tempo = plan.dialogue or (tables().dialogue.get(DEFAULT_DIALOGUE) if tables() else None)

    if fight_shot and plan.fight is not None and seconds:
        written = count_units(desc)
        expected = plan.fight.halves_for(seconds) - 1
        if not written:
            if expected >= 2:
                issues.append(UnitIssue(
                    _text_of("audit_shot.text"),
                    _text_of("audit_shot.text.2").format(seconds, expected),
                ))
        elif written < math.floor(expected * 0.6):
            issues.append(UnitIssue(
                _text_of("audit_shot.text.3"),
                _text_of("audit_shot.text.4").format(written, plan.fight.half, seconds, expected),
            ))
        elif written > math.ceil(expected * 1.5) + 1:
            issues.append(UnitIssue(
                _text_of("audit_shot.text.5"),
                _text_of("audit_shot.text.6").format(written, seconds, expected),
            ))
        long_lines = [turn for turn in turns if turn.chars > FIGHT_LINE_CHARS]
        if long_lines:
            issues.append(UnitIssue(
                _text_of("audit_shot.text.7"),
                _text_of("audit_shot.text.8").format(long_lines[0].speaker, long_lines[0].chars, FIGHT_LINE_CHARS),
            ))

    if tempo is not None and turns:
        cast = [name for name in characters if str(name).strip()]
        if len(cast) >= 2 and len(turns) == 1 and not fight_shot and seconds >= 2 * tempo.low:
            issues.append(UnitIssue(
                _text_of("audit_shot.text.9"),
                _text_of("audit_shot.text.10").format(len(cast), seconds, turns[0].speaker, tempo.name, tempo.turn),
            ))
        run = 1
        for previous, current in zip(labels, labels[1:]):
            run = run + 1 if current == previous else 1
            if run >= 3:
                issues.append(UnitIssue(_text_of("audit_shot.text.11"), _text_of("audit_shot.text.12").format(current)))
                break
        cap = tempo.budget() * LINE_BUDGET_SLACK
        heavy = next((turn for turn in turns if turn.chars > cap), None)
        if heavy is not None:
            issues.append(UnitIssue(
                _text_of("audit_shot.text.13"),
                _text_of("audit_shot.text.14").format(heavy.speaker, heavy.chars, tempo.name, tempo.budget(), cap),
            ))
        if not fight_shot and seconds:
            needed = sum(tempo.think + turn.chars / tempo.rate for turn in turns)
            empty = seconds - needed
            sighs = any(word in str(desc or "") for word in _SIGHS)
            if empty > tempo.tail and (sighs or empty > max(3.0, 2 * tempo.tail)):
                issues.append(UnitIssue(
                    _text_of("audit_shot.text.15"),
                    _text_of("audit_shot.text.16").format(needed, empty, tempo.name, tempo.tail),
                ))
    return issues


__all__ = [
    "DEFAULT_DIALOGUE", "DEFAULT_POWER", "DEFAULT_STYLE", "DialogueTempo", "FightTempo", "MartialTempo",
    "PowerTier", "ScenePlan", "Tables", "Turn", "UnitIssue", "audit_shot", "count_units", "has_lines", "judge_dialogue",
    "judge_power", "judge_style", "scene_plan", "split_turns", "tables",
]
