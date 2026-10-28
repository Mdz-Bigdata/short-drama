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
_NOT_WEAPONS = ("剑眉", "刀疤", "刀子嘴", "刀削", "眉如刀", "剑拔弩张")
# State adjustments of the code table (力量状态修正) that we can read off a character's own text.
_STATE_DROPS = (("重伤", 2), ("烂醉", 2), ("负伤", 1), ("受伤", 1), ("力竭", 1), ("醉酒", 1), ("醉醺醺", 1))
_SIGHS = ("叹气", "叹息", "长叹", "沉默", "无言", "对视", "怔怔", "愣住")
_U_LABEL = re.compile(r"U\s*(\d+)(?:\s*[–\-~～至]\s*U?\s*(\d+))?")
_BRACED = re.compile(r"[{｛]([^{}｛｝]+)[}｝]")
_NOTE = re.compile(r"[（(][^）)]*(?:[）)]|$)")
_QUOTES = re.compile(r"[「」『』“”\"'‘’\s]")
_STROKES = re.compile(r"[一-鿿A-Za-z0-9]")


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
        if len(row) < 6 or row[0] != "交互力量档":
            continue
        judged, _, craft = row[5].partition("；写法：")
        words = _words(judged.split("判定词：", 1)[1]) if "判定词：" in judged else ()
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
    line = next((item for item in text.splitlines() if item.startswith("力量档倍率")), "")
    multipliers = {f"IP{tier}": float(value) for tier, value in re.findall(r"IP(\d)\s*×\s*(\d+(?:\.\d+)?)", line)}
    crowd = re.search(r"多人戏\s*×\s*(\d+(?:\.\d+)?)", line)
    floor = re.search(r"不短于\s*(\d+(?:\.\d+)?)\s*秒", line)
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
             if word in content and not (word.startswith("醉") and "醉拳" in content)),
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
        lines = ["【单元环扣（本场节奏：武是接化发，文是听思答，一个 U 推进一个半单元）】"]
        if self.powers:
            described = "、".join(
                f"{name} {code} {data.powers[code].name}" for name, code in self.powers.items() if code in data.powers
            )
            if described:
                lines.append(f"- 交互力量档：{described}（判档：健康压过技能，技能压过年龄；负伤、力竭、醉酒降一档，醉拳不算醉）。")
        if self.fight is not None:
            lines.extend(self._fight_lines(data))
        elif self.calm_unit is not None:
            crafts = "；".join(
                f"{data.powers[code].name}：{data.powers[code].craft}"
                for code in dict.fromkeys(self.powers.values()) if code in data.powers and data.powers[code].craft
            )
            lines.append(
                f"- 动作单元：本场常态节奏一个动作单元约 {self.calm_unit:g} 秒（快慢不同的两人跟着慢的那个走）"
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
        style = f"{tempo.code} {tempo.name}" + ("" if fight.style_named else "（剧本没写流派，按散打）")
        counts = "、".join(
            f"{seconds} 秒约 {fight.halves_for(seconds)} 个半单元" for seconds in PREVIEW_SECONDS
        )
        crowd = f"，三人以上 ×{data.crowd:g}" if fight.crowd else ""
        pause = (
            f"段间停 {tempo.pause:g} 秒" if tempo.pause
            else "连绵不停，两段之间不写停"
        )
        return [
            f"- 打斗节奏：{style}，{fight.rule}，力量倍率 ×{fight.multiplier:g}{crowd} → 一个半单元约 {fight.half:.2g} 秒"
            f"（{fight.low:.2g}–{fight.high:.2g}）；起势 {tempo.opening:g} 秒，一段连招 {tempo.phrase[0]}–{tempo.phrase[1]} 个半单元，{pause}。"
            f"{tempo.traits}。",
            f"- 一格装几个：{counts}；U 数＝半单元数 − 1（U1 装两个半单元）。宁可多不可少：两个高手 9 秒只过两招就是太慢。",
            "- 打斗格的画面内容按 U 行写，每个 U 标起止秒：「U1（0.8–3.9秒）甲…；乙…」「U2（3.9–5.5秒）甲…」。"
            "U1＝起手＋对方第一次接化发；之后每个 U 只写新的那一个人：接（用什么迎住哪一招）→ 化（让线、转腰、后坐、带开）→ 发（发出什么、打向哪），"
            "上一 U 的发就是本 U 的来招，同一招不重播；同一人连续发起不超过两次；两段连招之间写「停（a–b秒）两人拉开对峙喘息」，停不放在格尾；"
            "倒地后先写起身再接站立的招；异兵器各用各的兵器接招；多人交锋一个 U 只写一个主交锋，其余人一句背景；最后一个 U 落点距格尾不超过 1.5 秒。",
        ]

    def _dialogue_lines(self) -> list[str]:
        tempo = self.dialogue
        assert tempo is not None
        named = "" if self.dialogue_named else "（剧本没写明对话性质，按日常交谈）"
        fight = f"打斗中的一句不超过 {FIGHT_LINE_CHARS} 字，落在化或发上（格开时一声喝、出手前一句狠话）；" if self.fight else ""
        return [
            f"- 台词节奏：{tempo.code} {tempo.name}{named} → 一轮约 {tempo.turn:g} 秒（{tempo.low:g}–{tempo.high:g}），"
            f"开口前停 {tempo.think:g} 秒，语速每秒约 {tempo.rate:g} 字，每轮约 {tempo.budget()} 字。",
            f"- 两人以上的对话一格至少两个话轮（一个完整来回）：台词栏按「说话人：台词」逐轮写，把对方的回应拉进同一格，不要一格只放一个人的一句；"
            f"每轮先写听的人的反应（眉、眼、呼吸），停半拍再开口，说话时身上有动作；同一时刻只有一人开口，其余人闭口给反应；"
            f"最后一句距格尾不超过 {tempo.tail:g} 秒，剩下的只给有内容的收尾动作（递出、起身、转身），不空叹；"
            f"三轮以上走起承转合（起立题、承推进、转翻转、合落定）；{fight}独白一人铺满，不造对话者。",
            "- 台词镜头：说者为主、听者为证——长句缓推说者、对方的肩留在画边；话尾插一拍听者的反应；换人开口越肩反打，不硬切。",
        ]


def _combine(data: Tables, powers: dict[str, str]) -> tuple[float, str]:
    """The pair's multiplier: one-sided → the stronger side's; otherwise the average (MX1/MX2)."""
    fighters = [code for code in powers.values() if code != "IP1" and code in data.multipliers]
    if not fighters:
        return data.multipliers.get(DEFAULT_POWER, 1.5), "力量档未判，按常人"
    ranks = sorted({int(code[2:]) for code in fighters})
    if len(ranks) == 1:
        code = f"IP{ranks[0]}"
        return data.multipliers[code], f"双方 {code} {data.powers[code].name}"
    strongest = f"IP{ranks[-1]}"
    if ranks[-1] - ranks[0] >= ONE_SIDED_GAP:
        return data.multipliers[strongest], f"相差三档以上一边倒，按强者 {strongest}（强者可连续发起三次，弱者只接不还）"
    average = sum(data.multipliers[code] for code in fighters) / len(fighters)
    return round(average, 3), "对抗取平均"


_QUOTED = re.compile(r"[「“\"][^」”\"]{2,}[」”\"]")


def has_lines(text: str, cast: Sequence[str] = ()) -> bool:
    """Whether the scene has spoken lines: a named speaker label, a 【name】 line, or quoted speech."""
    content = str(text or "")
    if _QUOTED.search(content) or re.search(r"(?m)^\s*【[^】]{1,12}】", content):
        return True
    return bool(_labels(content, cast)) if cast else bool(re.search(r"(?m)^\s*[一-鿿·]{1,8}(?:[（(][^）)]*[）)])?\s*[：:]", content))


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
            powers = {"本场人物": scene_power}
    plan = ScenePlan(powers=powers)

    if fight:
        frail = [name for name, code in powers.items() if code == "IP1"]
        if frail:
            plan.notes.append(f"{'、'.join(frail)} 是 IP1 衰竭：不进武打交锋，动作小而慢，每个动作前先有一口气。")
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
                    "打斗未按单元环扣写",
                    f"这格 {seconds:g} 秒按本场节奏约 {expected} 个 U，画面内容没有写 U 行；按「U1（a–b秒）…」逐个写出谁接谁、怎么化、发出什么",
                ))
        elif written < math.floor(expected * 0.6):
            issues.append(UnitIssue(
                "打斗单元过少",
                f"写了 {written} 个 U，本场节奏（一个半单元约 {plan.fight.half:.2g} 秒）{seconds:g} 秒约 {expected} 个；过招太慢，补上接化发",
            ))
        elif written > math.ceil(expected * 1.5) + 1:
            issues.append(UnitIssue(
                "打斗单元过密",
                f"写了 {written} 个 U，本场节奏 {seconds:g} 秒约 {expected} 个；匀速塞满不真实，两段连招之间要停",
            ))
        long_lines = [turn for turn in turns if turn.chars > FIGHT_LINE_CHARS]
        if long_lines:
            issues.append(UnitIssue(
                "打斗台词过长",
                f"{long_lines[0].speaker} 一句 {long_lines[0].chars} 字；打斗里的一句不超过 {FIGHT_LINE_CHARS} 字，长对白放到开打前后",
            ))

    if tempo is not None and turns:
        cast = [name for name in characters if str(name).strip()]
        if len(cast) >= 2 and len(turns) == 1 and not fight_shot and seconds >= 2 * tempo.low:
            issues.append(UnitIssue(
                "对话少于一个来回",
                f"{len(cast)} 人在场、{seconds:g} 秒只有 {turns[0].speaker} 一轮；按 {tempo.name} 一轮约 {tempo.turn:g} 秒，"
                "把对方的回应拉进这一格，或把这一格缩短",
            ))
        run = 1
        for previous, current in zip(labels, labels[1:]):
            run = run + 1 if current == previous else 1
            if run >= 3:
                issues.append(UnitIssue("一人连说三句", f"{current} 连着说了三句，另一个人一直站着；中间给对方一轮"))
                break
        cap = tempo.budget() * LINE_BUDGET_SLACK
        heavy = next((turn for turn in turns if turn.chars > cap), None)
        if heavy is not None:
            issues.append(UnitIssue(
                "话轮台词超字数",
                f"{heavy.speaker} 一轮 {heavy.chars} 字，{tempo.name} 一轮约 {tempo.budget()} 字（上限 {cap:.0f}）；删字或给这一轮加秒",
            ))
        if not fight_shot and seconds:
            needed = sum(tempo.think + turn.chars / tempo.rate for turn in turns)
            empty = seconds - needed
            sighs = any(word in str(desc or "") for word in _SIGHS)
            if empty > tempo.tail and (sighs or empty > max(3.0, 2 * tempo.tail)):
                issues.append(UnitIssue(
                    "格尾空叹",
                    f"台词约 {needed:.1f} 秒说完，格尾空 {empty:.1f} 秒（{tempo.name} 余量 {tempo.tail:g} 秒）；"
                    "加一轮、写足台词，或给一个有内容的收尾动作，不要只叹气对视",
                ))
    return issues


__all__ = [
    "DEFAULT_DIALOGUE", "DEFAULT_POWER", "DEFAULT_STYLE", "DialogueTempo", "FightTempo", "MartialTempo",
    "PowerTier", "ScenePlan", "Tables", "Turn", "UnitIssue", "audit_shot", "count_units", "has_lines", "judge_dialogue",
    "judge_power", "judge_style", "scene_plan", "split_turns", "tables",
]
