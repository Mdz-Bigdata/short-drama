# -*- coding: utf-8 -*-
"""Sound effects bound to what the picture shows, for models that render sound themselves.

A model that hears "脚步声、关门声、杯子声、雨声" gets a pile of sounds and places them
wherever it likes: the cup lands before the hand reaches the counter, the door bangs twice.
So the shot's sound cues are rewritten as three things:

- **one ambience bed** — the room or the street, continuous and low, under everything;
- **at most two key contacts**, each tied to a moment the camera actually sees and written
  as material + action + distance + how the room sounds around it, e.g.
  「纸杯杯底碰到木柜台的瞬间：一声近处、轻短、偏闷的接触声」, followed by "the next
  movement does not make that sound again";
- the dialogue kept clear above the bed, and an explicit list of what is not in the clip.

A contact cue with no visible event in the shot is left out (and reported): an unbound sound
is exactly the one the model plays early or late.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.core import prompt_data

# 词表与说法都是数据(app/data/prompt/sound_events.json)：哪些标签是铺底、哪些动作是什么声、材质听起来如何。
_DATA = "sound_events"
MAX_CONTACTS = prompt_data.number(_DATA, "max_contacts")

# 标签决定一条声音线索是环境铺底还是接触音效。
_BED_LABELS = prompt_data.words(_DATA, "bed_labels")
_CONTACT_LABELS = prompt_data.words(_DATA, "contact_labels")
_BED_WORDS = prompt_data.words(_DATA, "bed_words")
# 动作 → (力度, 声音类别)。顺序即优先级：先认更具体的动作；打戏的接触音排最前。
_CONTACT_KINDS: tuple[tuple[tuple[str, ...], str, str], ...] = tuple(
    (tuple(str(verb) for verb in verbs), str(strength), str(kind)) for verbs, strength, kind in prompt_data.value(_DATA, "contact_kinds")
)
_FIGHT_SOUNDS = prompt_data.words(_DATA, "fight_sounds")
_MATERIALS: tuple[tuple[tuple[str, ...], str], ...] = tuple(
    (tuple(str(word) for word in words), str(quality)) for words, quality in prompt_data.value(_DATA, "materials")
)
_NOISY_BED = prompt_data.words(_DATA, "noisy_bed")
# 不指向具体声源的套话：只说明"有环境声"，不进铺底。
_FILLERS = prompt_data.words(_DATA, "fillers")
_SOUND_SUFFIX = prompt_data.pattern(_DATA, "sound_suffix")
_ONOMATOPOEIA = prompt_data.pattern(_DATA, "onomatopoeia")
_CLAUSE = re.compile(r"[，,。；;！？!?\n]")


@dataclass(frozen=True)
class ContactSound:
    """One key sound, tied to the moment the camera sees it happen."""

    event: str
    sound: str

    def line(self) -> str:
        return f"{self.event}的瞬间：{self.sound}。"


@dataclass
class SoundEventPlan:
    bed: str
    contacts: list[ContactSound] = field(default_factory=list)
    dialogue: bool = False
    exclusions: list[str] = field(default_factory=list)
    # 写了却在画面里找不到对应动作的音效：不写进提示词，留给后期。
    unbound: list[str] = field(default_factory=list)

    def contact_lines(self) -> list[str]:
        if not self.contacts:
            return []
        lines = [contact.line() for contact in self.contacts]
        lines.append("每声只在该瞬间响一次，随后的动作不再重复这一声。")
        return lines

    def lines(self) -> list[str]:
        lines = [f"环境铺底：{self.bed}，全程连续、音量压低，只作背景。"]
        lines.extend(self.contact_lines())
        if self.dialogue:
            lines.append("对白清晰，始终在环境铺底之上。")
        if self.exclusions:
            lines.append("、".join(self.exclusions) + "。")
        return lines

    @property
    def text(self) -> str:
        return "\n".join(self.lines())

    def as_dict(self) -> dict:
        return {
            "bed": self.bed, "contacts": [{"event": c.event, "sound": c.sound} for c in self.contacts],
            "dialogue": self.dialogue, "exclusions": list(self.exclusions), "unbound": list(self.unbound),
        }


def split_cues(cues: str | Sequence[str]) -> tuple[list[str], list[str]]:
    """``(ambience, contacts)`` from the shot's sound note, by label first and words second."""
    parts = [cues] if isinstance(cues, str) else list(cues)
    beds: list[str] = []
    contacts: list[str] = []
    for part in parts:
        for chunk in re.split(r"[；;\n]", str(part or "")):
            chunk = chunk.strip()
            if not chunk or any(filler in chunk for filler in _FILLERS):
                continue
            label, _, body = chunk.partition("：") if "：" in chunk else chunk.partition(":")
            if not body:
                label, body = "", chunk
            label = label.strip()
            for item in re.split(r"[、，,]", body):
                item = item.strip()
                if not item:
                    continue
                if any(label.startswith(word) for word in _CONTACT_LABELS):
                    contacts.append(item)
                elif any(label.startswith(word) for word in _BED_LABELS):
                    beds.append(item)
                elif _contact_kind(item) and not any(word in item for word in _BED_WORDS):
                    contacts.append(item)
                else:
                    beds.append(item)
    return list(dict.fromkeys(beds)), list(dict.fromkeys(contacts))


def _contact_kind(text: str) -> tuple[str, str] | None:
    for verbs, strength, kind in _CONTACT_KINDS:
        if any(verb in text for verb in verbs):
            return strength, kind
    return None


def _core(cue: str) -> str:
    return _SOUND_SUFFIX.sub("", _ONOMATOPOEIA.sub("", cue)).strip()


def _visible_clause(cue: str, clauses: Sequence[str], props: Sequence[str]) -> str:
    """The clause of the action that shows ``cue`` happening, or "" when nothing on screen does."""
    core = _core(cue)
    keys = [prop for prop in props if prop and prop in core]
    # 「拳肉闷响」这条线索绑的是打中那一下：线索命中的那类声音，它的所有动作词都算这条线索的事件。
    keys += [verb for verbs, _, _ in _CONTACT_KINDS if any(verb in core for verb in verbs) for verb in verbs if len(verb) >= 2]
    keys += [verb for verbs, _, _ in _CONTACT_KINDS for verb in verbs if len(verb) >= 2 and verb in core]
    keys += [core[i:i + 2] for i in range(len(core) - 1) if re.fullmatch(r"[一-鿿]{2}", core[i:i + 2])]
    for key in keys:
        for clause in clauses:
            if key in clause:
                return clause
    return ""


def _distance(shot_size: str) -> str:
    if any(word in shot_size for word in ("特写", "近景")):
        return "近处"
    if "中景" in shot_size:
        return "中近距离"
    if any(word in shot_size for word in ("全景", "远景")):
        return "稍远、带一点空间感"
    return ""


def _describe(clause: str, cue: str, *, shot_size: str, bed: str) -> str:
    strength, kind = _contact_kind(f"{clause}{cue}") or ("短", "接触声")
    text = f"{clause}{cue}"
    materials = [quality for words, quality in _MATERIALS if any(word in text for word in words)][:2]
    parts = [part for part in (_distance(shot_size), strength, *materials) if part]
    room = "在嘈杂的环境里仍能分辨" if any(word in bed for word in _NOISY_BED) else "在安静的环境里清楚可辨"
    return f"一声{'、'.join(parts)}的{kind}，{room}"


def build_sound_events(
    cues: str | Sequence[str],
    *,
    action: str,
    props: Sequence[str] = (),
    shot_size: str = "",
    dialogue: bool = False,
    narration: bool = False,
    music: bool = False,
) -> SoundEventPlan:
    """The shot's sound as one bed, up to two event-bound contacts, and what is left out.

    Contacts come from the sound note first; when the note names none, a contact the action
    itself performs on screen (放下、敲、关门…) is used. ``narration`` / ``music`` say the shot
    plans a voice-over or a score, which keeps them off the exclusion list.
    """
    beds, cue_contacts = split_cues(cues)
    bed = "、".join(beds) or "轻微的空间底噪"
    # 台词原文({…} 里的话、「原文台词保持不变：」之后)不是可见事件：先去掉，再按标点拆分句——
    # 否则「{谁？}停顿一拍{谁动的剑？}」会被拆成「} 停顿一拍 {谁动的剑」这样的碎片当成音效事件。
    visible = re.split(r"原文台词保持不变[：:]", str(action or ""), maxsplit=1)[0]
    visible = re.sub(r"[{｛][^{}｛｝]*[}｝]", "", visible)
    clauses = [clause.strip() for clause in _CLAUSE.split(visible) if clause.strip() and not re.search(r"[{}｛｝]", clause)]
    # 台词原文混在动作里时不算可见事件。
    clauses = [clause for clause in clauses if "：" not in clause and ":" not in clause and "台词" not in clause]
    props = [str(prop).strip() for prop in props if str(prop).strip()]

    contacts: list[ContactSound] = []
    unbound: list[str] = []
    used: set[str] = set()
    for cue in cue_contacts:
        clause = _visible_clause(cue, clauses, props)
        if not clause:
            unbound.append(cue)
            continue
        if clause in used or len(contacts) >= MAX_CONTACTS:
            continue
        used.add(clause)
        contacts.append(ContactSound(event=clause, sound=_describe(clause, cue, shot_size=shot_size, bed=bed)))
    # 声音线索没绑到任何可见事件时(线索是「拳肉闷响」、这一镜却没打中谁)，退回到动作本身做的接触。
    if not contacts:
        for clause in clauses:
            if len(contacts) >= MAX_CONTACTS:
                break
            kind = _contact_kind(clause)
            # 打中人不需要道具或材质词：皮肉本身就是接触面。
            touches = any(prop in clause for prop in props) or any(
                word in clause for words, _ in _MATERIALS for word in words
            ) or (kind is not None and kind[1] in _FIGHT_SOUNDS)
            if kind and touches and clause not in used:
                used.add(clause)
                contacts.append(ContactSound(event=clause, sound=_describe(clause, "", shot_size=shot_size, bed=bed)))

    exclusions = [
        *([] if narration else ["无旁白"]),
        *([] if music else ["无音乐"]),
        *(["无额外对白"] if dialogue else ["无对白"]),
    ]
    return SoundEventPlan(bed=bed, contacts=contacts, dialogue=dialogue, exclusions=exclusions, unbound=unbound)


__all__ = ["MAX_CONTACTS", "ContactSound", "SoundEventPlan", "build_sound_events", "split_cues"]
