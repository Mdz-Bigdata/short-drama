# -*- coding: utf-8 -*-
"""The layered video prompt of one shot.

Every clip prompt is built the same way, in the same order, so the model reads the same
thing in the same place every time:

1. ``[STYLE LOCK]`` — the style pack's lock verbatim, then this segment's tone line.
2. **Asset anchors** — 【人物锚点·锁脸】/【场景锚点·锁场景】/【道具锚点】 name every character, scene and
   prop this shot locks as ``@[名字]`` (see :mod:`app.core.asset_mentions`), then what each reference
   image, video or audio is for. The same ``@[名字]`` marks appear wherever the body names an asset;
   they are resolved to "名字（参考图N）" right before the prompt is sent.
3. **Structure** — length, single shot or cut count, first / last frame, the transition in.
4. **Locks** — space, state, props, light, sound: the continuity tags, before the picture,
   because the front of a prompt weighs most. Lighting numbers live here and nowhere else.
5. **Shot block** — 景别/运镜, 构图, picture, background, end state, timeline, dialogue
   (each line written as ``@[说话人]{台词}``).
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

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from app.core import prompt_budget
from app.core.asset_mentions import mark_mentions, mention
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
    # 本镜锁定的资产名字(按参考图顺序)：写进锚点行，并在正文里标成 @[名字]。
    cast_refs: Sequence[str] = ()
    scene_refs: Sequence[str] = ()
    prop_refs: Sequence[str] = ()
    # 构图：主体在画面里的位置与前中后景安排(见 shot-design-master 构图速查)。
    composition: str = ""


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
    # No absolute seconds in the text: the clip length travels as the request's duration, and
    # video models (Seedance's own prompt rules among them) follow shot order and the start /
    # end frame far more reliably than "0-8秒" ranges, which they treat as frame-exact cues.
    structure = [
        f"单镜连续画面，一镜到底不切镜 + 画幅{shot.aspect_ratio}",
        "以所给首帧起始" if shot.first_frame else "无首帧，按描述建立画面",
    ]
    if shot.last_frame:
        structure.append("以所给尾帧结束")
    if cut_label:
        structure.append(f"切入本镜：{cut_label}")
    anchors = [note.strip().rstrip("。") + "。" for note in shot.reference_notes if str(note).strip()]
    timeline = f"{shot.carry_in}{shot.subject_action}".strip()
    camera = f"景别：{shot.shot_size}；运镜：{shot.camera_movement}"
    dialogue = (
        f"台词（逐字保持原文，口型同步）：{format_dialogue(shot.dialogue, shot.characters)}"
        if shot.dialogue.strip() else "无台词，人物闭口。"
    )
    end_state = f"落幅：{shot.end_state}"
    rules = iron_rules(pack, subjects=list(shot.characters), reference_kinds=list(shot.reference_kinds), rule_ids=["physics", "lip_sync"] if shot.dialogue.strip() else ["physics"])
    rules.extend(str(item).strip() for item in shot.continuity_constants if str(item).strip())

    sections: dict[str, str] = {
        "style_lock": style_lock_block(pack, shot.tone),
        **_asset_anchor_sections(shot),
        "anchors": ("【参考素材职责】\n" + "\n".join(anchors)) if anchors else "",
        "structure": "【结构声明】" + " + ".join(structure) + "。",
        "locks": _lock_lines(shot),
        "camera": camera,
        "subject": f"画面：{timeline}。",
        "motion": shot.motion_prompt.strip(),
        "expression": f"表演：{shot.expression.strip()}" if shot.expression.strip() else "",
        "composition": f"构图：{shot.composition.strip()}" if shot.composition.strip() else "",
        "environment": f"背景：{shot.environment.strip()}" if shot.environment.strip() else "",
        "colour": "\n".join(line.strip() for line in shot.palette_lines if str(line).strip()),
        "effects": f"特效：{_join(shot.effects)}" if _join(shot.effects) else "",
        "contact": contact_line(shot.subject_action, [*shot.props, *shot.prop_refs]),
        "dialogue": dialogue,
        "dialogue_notes": f"台词表达：{shot.dialogue_notes.strip()}" if shot.dialogue_notes.strip() and shot.dialogue.strip() else "",
        "end_state": end_state,
        "sound_layers": f"【声音设计·三层】{shot.sound_layers.strip()}" if shot.sound_layers.strip() else "",
        "sound": f"【声音设计】{shot.sound.strip()}" if shot.sound.strip() and not shot.sound_layers.strip() else "",
        "closing": pack.sound.closing_sentence,
        "rules": "【关键约束】\n" + "\n".join(rules),
        "negatives": " + ".join(negatives),
    }
    names = [*shot.cast_refs, *shot.scene_refs, *shot.prop_refs]
    for key in _MARKED_SECTIONS:
        if sections.get(key):
            sections[key] = mark_mentions(sections[key], names)
    kept, report = prompt_budget.compress(sections, model, main="subject")
    text = _render(kept)
    report.total_length = prompt_budget.prompt_length(text)
    return CompiledVideoPrompt(text=text, sections=kept, pressure=report, style_pack=pack.id, negatives=negatives)


_ORDER = (
    "style_lock", "anchor_cast", "anchor_scene", "anchor_props", "anchors", "structure", "locks", "camera",
    "composition", "subject", "motion", "expression", "environment",
    "colour", "effects", "contact", "dialogue", "dialogue_notes", "end_state", "sound_layers", "sound", "closing", "rules", "negatives",
)
_BLANK_BEFORE = frozenset({"anchor_cast", "structure", "locks", "camera", "sound_layers", "sound", "rules"})
# 正文里出现资产名字就标成 @[名字] 的小节；风格锁、素材职责、铁律和负面词不标。
_MARKED_SECTIONS = (
    "locks", "camera", "composition", "subject", "motion", "expression", "environment", "effects", "contact",
    "dialogue", "dialogue_notes", "end_state",
)


# Verbs that put a prop in someone's hand, and the kind of contact each one asks for.
_SUPPORT_VERBS = ("托", "捧", "端")
_REST_VERBS = ("扶", "撑", "按住", "按在", "搭在")
_GRIP_VERBS = ("握", "攥", "拿", "持", "举", "提", "抓", "捏", "递", "接过", "抱")


def contact_line(action: str, props: Sequence[str]) -> str:
    """How a hand meets the prop the shot puts in it, so the hand is not pasted beside the object.

    Holding is written as contact, not possession: which hand, how it grips, supports or
    rests, which part of the object it touches, and what covers what. Only written when
    the action actually handles one of the shot's props.
    """
    action = str(action or "")
    named = [str(item).strip() for item in props if str(item).strip() and str(item).strip() in action]
    if not named or not any(verb in action for verb in (*_SUPPORT_VERBS, *_REST_VERBS, *_GRIP_VERBS)):
        return ""
    prop = named[0]
    if any(verb in action for verb in _SUPPORT_VERBS):
        how = f"掌心朝上呈碗状承住{prop}的下半部，指腹贴住下侧，{prop}底部与手掌接触不悬空"
    elif any(verb in action for verb in _REST_VERBS):
        how = f"掌根与放松的手指平贴在{prop}的受力面上，手腕自然弯曲，身体重量不压在手上"
    else:
        how = f"四指环绕{prop}的握持处、拇指与其余手指相对，前侧手指自然遮住一部分{prop}，{prop}从手的上下两端露出且方向连贯"
    return f"持物接触：{how}；左右按角色自身的身体判断，接触处清楚，手腕与前臂自然相连。"


def _asset_anchor_sections(shot: ShotPromptInput) -> dict[str, str]:
    """锚点行：本镜锁定的人物、场景、道具，各自以 @[名字] 列出，写明锁什么、放开什么。"""
    def names(items: Sequence[str]) -> str:
        return "、".join(mention(str(item).strip()) for item in dict.fromkeys(items) if str(item).strip())

    cast, scenes, props = names(shot.cast_refs), names(shot.scene_refs), names(shot.prop_refs)
    return {
        "anchor_cast": (
            f"【人物锚点·锁脸】{cast}。脸型、发型、服装与体型以参考图为准，"
            "只随剧情改变表情、姿态与动作，情绪前后连贯。"
        ) if cast else "",
        "anchor_scene": (
            f"【场景锚点·锁场景】{scenes}。灯光色调、空间布局与环境动态保持一致；"
            "换到新场景时先交代它的主光方向与空间。"
        ) if scenes else "",
        "anchor_props": f"【道具锚点】{props}。外形、材质、颜色与持有关系保持一致。" if props else "",
    }


def format_dialogue(dialogue: str, speakers: Sequence[str]) -> str:
    """台词逐行写成 ``@[说话人]{台词}``；认不出说话人的行(旁白、画外音)只用花括号括起原文。"""
    known = sorted({str(name).strip() for name in speakers if str(name).strip()}, key=len, reverse=True)
    lines: list[str] = []
    for raw in (dialogue or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        for name in known:
            # 「姜照：……」或「姜照（平静）：……」——括号里的语气原样保留在说话人后面。
            matched = re.match(re.escape(name) + r"\s*([（(][^）)]{1,20}[）)])?\s*[：:]\s*(.*)$", line)
            if matched:
                delivery = matched.group(1) or ""
                lines.append(f"{mention(name)}{delivery}{{{matched.group(2).strip()}}}")
                break
        else:
            lines.append(f"{{{line}}}")
    return " ".join(lines)


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
