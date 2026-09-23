# -*- coding: utf-8 -*-
"""The layered video prompt of one shot.

Every clip prompt is built the same way, in the same order, so the model reads the same
thing in the same place every time:

1. ``[STYLE LOCK]`` — the style pack's lock verbatim, then this segment's tone line.
2. **Anchors** — what each reference image, video or audio is for.
3. **Structure** — length, single shot or cut count, first / last frame, the transition in.
4. **Locks** — space, state, props, light, sound: the continuity tags, before the picture,
   because the front of a prompt weighs most. Lighting numbers live here and nowhere else.
5. **Shot block** — camera, picture, background, end state, timeline, dialogue.
6. **Sound** — layers for this shot, then the closing sentence (no BGM, no subtitles).
   A model that renders sound with the picture gets its named layers here instead,
   and those are never cut: for it, the sound *is* half the deliverable.
7. **Named rules** and the negative list.

The budget applies to the body: the style lock, anchors, rules, negatives and the closing
sentence are restated on every prompt and are not measured. The optional body sections
(sound layers, environment detail, colour, effects, delivery notes) are cut in that order
when the body is over the target model's budget; the locks, the subject, the action, the
camera and the dialogue never are. The result carries a pressure report so the shot
workspace can show what was cut.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from app.core import prompt_budget
from app.core.style_packs import StylePack, iron_rules, negatives_for, style_lock_block
from app.core.video_references import MIN_SHOT_SECONDS

_LOCK_TAGS = (("space", "[空间锚]"), ("state", "[状态锁]"), ("props", "[道具锁]"), ("light", "[光影锁]"), ("sound", "[声音锁]"))
# A clip prompt stands on its own: it may not refer back to a batch the model never saw.
_FORBIDDEN_SHORTHANDS = ("同上", "同前", "延续上一批次", "场景不变", "人物位置不变", "继续刚才的对峙")


@dataclass
class ShotPromptInput:
    shot_index: int
    duration_seconds: int
    shot_size: str
    camera_movement: str
    subject_action: str
    scene: str
    blocking: str
    start_state: str
    end_state: str
    eyeline: str = ""
    props: Sequence[str] = ()
    characters: Sequence[str] = ()
    lighting: str = ""
    sound: str = ""
    # A model that generates sound with the picture (MiniMax H3) gets its three
    # named layers here; unlike the sound note, this one is never cut away.
    sound_layers: str = ""
    dialogue: str = ""
    dialogue_notes: str = ""
    effects: Sequence[str] = ()
    environment: str = ""
    expression: str = ""
    motion_prompt: str = ""
    carry_in: str = ""
    cut_in: Mapping[str, object] | None = None
    reference_notes: Sequence[str] = ()
    reference_kinds: Sequence[str] = ()
    first_frame: bool = True
    last_frame: bool = False
    tone: Mapping[str, str] | str | None = None
    palette_lines: Sequence[str] = ()
    situations: Sequence[str] = ()
    extra_negatives: Sequence[str] = ()
    continuity_constants: Sequence[str] = ()
    aspect_ratio: str = "9:16"


@dataclass
class CompiledVideoPrompt:
    text: str
    sections: dict[str, str]
    pressure: prompt_budget.PressureReport
    style_pack: str
    negatives: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"style_pack": self.style_pack, "pressure": self.pressure.as_dict(), "sections": list(self.sections)}


def _join(items: Sequence[str]) -> str:
    return "、".join(str(item).strip() for item in items if str(item).strip())


def _lock_lines(shot: ShotPromptInput) -> str:
    props = _join(shot.props) or "无关键道具"
    cast = _join(shot.characters) or "本镜人物"
    values = {
        "space": f"{shot.scene}；{shot.blocking}",
        "state": f"{cast}：{shot.start_state}" + (f"；视线：{shot.eyeline}" if shot.eyeline else ""),
        "props": props,
        "light": shot.lighting or "延续上一镜主光方向、色温与光比",
        "sound": shot.sound or "延续上一镜环境底噪",
    }
    return "\n".join(f"{tag}{values[key]}" for key, tag in _LOCK_TAGS)


def compile_shot_prompt(
    pack: StylePack, shot: ShotPromptInput, *, model: str, max_duration_seconds: int | None = None,
) -> CompiledVideoPrompt:
    """The prompt for one clip, sectioned, then fitted to ``model``'s budget.

    The clip length must be inside the selected model's range, and the space the prompt
    describes must be restated in full — a clip prompt cannot say "same as above" about a
    batch the model never saw.
    """
    ceiling = max(MIN_SHOT_SECONDS, int(max_duration_seconds or 0) or 15)
    if not MIN_SHOT_SECONDS <= shot.duration_seconds <= ceiling:
        raise ValueError(f"clip duration must be between {MIN_SHOT_SECONDS} and {ceiling} seconds")
    restated = f"{shot.scene} {shot.blocking} {shot.start_state}"
    if any(shortcut in restated for shortcut in _FORBIDDEN_SHORTHANDS):
        raise ValueError("space, blocking and start state must be restated in full")
    situations = list(shot.situations)
    if len(shot.characters) >= 2 and "multi_person" not in situations:
        situations.append("multi_person")
    negatives = negatives_for(pack, situations, shot.extra_negatives)
    cut = dict(shot.cut_in or {})
    cut_label = str(cut.get("label") or "")
    structure = [
        f"整段{shot.duration_seconds}秒单镜连续画面 + 画幅{shot.aspect_ratio}",
        "以所给首帧起始" if shot.first_frame else "无首帧，按描述建立画面",
    ]
    if shot.last_frame:
        structure.append("以所给尾帧结束")
    if cut_label:
        structure.append(f"切入本镜：{cut_label}")
    anchors = [note.strip().rstrip("。") + "。" for note in shot.reference_notes if str(note).strip()]
    timeline = f"0-{shot.duration_seconds}秒：{shot.carry_in}{shot.subject_action}".strip()
    camera = f"机位：{shot.shot_size}，{shot.camera_movement}"
    dialogue = f"台词（逐字保持原文，口型同步）：{shot.dialogue}" if shot.dialogue.strip() else "无台词，人物闭口。"
    end_state = f"末段：{shot.end_state}"
    rules = iron_rules(pack, subjects=list(shot.characters), reference_kinds=list(shot.reference_kinds), rule_ids=["physics", "lip_sync"] if shot.dialogue.strip() else ["physics"])
    rules.extend(str(item).strip() for item in shot.continuity_constants if str(item).strip())

    sections: dict[str, str] = {
        "style_lock": style_lock_block(pack, shot.tone),
        "anchors": ("【参考素材职责】\n" + "\n".join(anchors)) if anchors else "",
        "structure": "【结构声明】" + " + ".join(structure) + "。",
        "locks": _lock_lines(shot),
        "camera": camera,
        "subject": f"画面：{timeline}。",
        "motion": shot.motion_prompt.strip(),
        "expression": f"表演：{shot.expression.strip()}" if shot.expression.strip() else "",
        "environment": f"背景：{shot.environment.strip()}" if shot.environment.strip() else "",
        "colour": "\n".join(line.strip() for line in shot.palette_lines if str(line).strip()),
        "effects": f"特效：{_join(shot.effects)}" if _join(shot.effects) else "",
        "dialogue": dialogue,
        "dialogue_notes": f"台词表达：{shot.dialogue_notes.strip()}" if shot.dialogue_notes.strip() and shot.dialogue.strip() else "",
        "end_state": end_state,
        "sound_layers": f"【声音设计·三层】{shot.sound_layers.strip()}" if shot.sound_layers.strip() else "",
        "sound": f"【声音设计】{shot.sound.strip()}" if shot.sound.strip() and not shot.sound_layers.strip() else "",
        "closing": pack.sound.closing_sentence,
        "rules": "【关键约束】\n" + "\n".join(rules),
        "negatives": " + ".join(negatives),
    }
    kept, report = prompt_budget.compress(sections, model, main="subject")
    text = _render(kept)
    report.total_length = prompt_budget.prompt_length(text)
    return CompiledVideoPrompt(text=text, sections=kept, pressure=report, style_pack=pack.id, negatives=negatives)


_ORDER = (
    "style_lock", "anchors", "structure", "locks", "camera", "subject", "motion", "expression", "environment",
    "colour", "effects", "dialogue", "dialogue_notes", "end_state", "sound_layers", "sound", "closing", "rules", "negatives",
)
_BLANK_BEFORE = frozenset({"anchors", "structure", "locks", "camera", "sound_layers", "sound", "rules"})


def _render(sections: Mapping[str, str]) -> str:
    lines: list[str] = []
    for key in _ORDER:
        value = str(sections.get(key) or "").strip()
        if not value:
            continue
        if key in _BLANK_BEFORE and lines:
            lines.append("")
        lines.append(value)
    return "\n".join(lines)


def extension_prompt(pack: StylePack, *, source_ref: str, seconds: int, continuation: str, mask: str = "") -> str:
    """The prompt that extends a generated clip: continuity first, the look restated last."""
    parts = [
        f"参考{source_ref}的内容，延长视频{seconds}s向后延长。要求延长自然、动作衔接流畅，禁止生硬切镜、禁止物体凭空出现。",
        continuation.strip(),
    ]
    if mask.strip():
        parts.append(
            f"需要在切镜处使用“遮罩转场”：{mask.strip()}完全遮挡镜头使画面变暗，随后镜头穿过{mask.strip()}拉开，直接显现出下一个场景。"
        )
    parts.append(pack.extension_restatement)
    parts.append(pack.sound.closing_sentence)
    return "\n".join(part for part in parts if part)


__all__ = ["CompiledVideoPrompt", "ShotPromptInput", "compile_shot_prompt", "extension_prompt"]
