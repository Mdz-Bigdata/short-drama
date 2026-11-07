# -*- coding: utf-8 -*-
"""The layered video prompt of one shot.

Every clip prompt is built the same way, in the same order, so the model reads the same
thing in the same place every time. It is the three paragraphs of the 《运镜提示词》 template:

**Pa1 — who is in it and what happens.**

1. **Asset anchors** — 【人物锚点·锁脸】/【场景锚点·锁场景】/【道具锚点】 name every character, scene and
   prop this shot locks as ``@[名字]`` (see :mod:`app.core.asset_mentions`), then what each reference
   image, video or audio is for (只用于 / 不采用). The same ``@[名字]`` marks appear wherever the body
   names an asset; they are resolved to "名字（参考图N）" right before the prompt is sent.
   The cast line also declares the people distinct (one appearance each, several references of
   one person are one person), and 【服装绑定】 ties each wearer to their costume reference.
2. **Structure** — length, single shot or cut count, first / last frame, the transition in.
3. **Locks** — space, state, props (with who holds what), light, sound: the continuity tags,
   before the picture, because the front of a prompt weighs most. Lighting numbers live here
   and nowhere else.
4. **Shot block** — 景别/运镜, 构图, picture, background, end state, timeline, dialogue
   (each line written as ``@[说话人]{台词}``).

**Pa2 — what it looks and sounds like.**

5. ``[STYLE LOCK]`` — the style pack's lock verbatim, then this segment's tone line; then
   每位人物的外貌简述 and the pack's 画质 paragraph (materials, light physics, motion blur).
6. **Sound** — one ambience bed plus at most two contacts bound to visible events
   (:mod:`app.core.sound_events`), then the closing sentence (no BGM, no subtitles).
   MiniMax H3 gets its named layers here instead, and those are never cut: for it, the
   sound *is* half the deliverable. A model that renders no sound gets no sound wording
   at all — its dialogue and effects are laid in afterwards.

**Pa3 — the rules.**

7. **Named rules** (physics over the reference, form continuity, identity, lip sync…) and the
   negative list.

The budget applies to the body: the style lock, anchors, rules, negatives and the closing
sentence are restated on every prompt and are not measured. The optional body sections
(sound layers, environment detail, colour, effects, delivery notes) are cut in that order
when the body is over the target model's budget; the locks, the subject, the action, the
camera and the dialogue never are. The result carries a pressure report so the shot
workspace can show what was cut.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace

from app.core import prompt_budget, prompt_data
from app.core.asset_mentions import mark_mentions, mention
from app.core.face_card import framing_for_shot_size, parse_face_card, render_face_card
from app.core.prompt_distiller import dedupe, is_no_line
from app.core.screenwriting.speech import is_narrator
from app.core.spatial_stage import clip_brief
from app.core.spoken_lines import dialogue_segments, split_speech
from app.core.sound_events import build_sound_events, split_cues
from app.core.storyboard_director import space_restatement
from app.core.style_packs import SIGNAGE_RULE, StylePack, iron_rules, negatives_for, style_lock_block
from app.core.video_references import MIN_SHOT_SECONDS

# 词表、标签、句式都是数据(app/data/prompt/clip_prompt.json)：这里只读。
_DATA = "clip_prompt"
_LOCK_TAGS = prompt_data.pairs(_DATA, "lock_tags")
# A clip prompt stands on its own: it may not refer back to a batch the model never saw.
_FORBIDDEN_SHORTHANDS = prompt_data.words(_DATA, "forbidden_shorthands")


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
    # 导演台上这一镜的姿态、姿势、动作、位置、朝向、空间与机位，一行一件事(见 spatial_stage.clip_brief)。
    stage_lines: Sequence[str] = ()
    # 服装参考图绑定到穿它的人：(穿着者, 造型名)。
    costume_refs: Sequence[tuple[str, str]] = ()
    # 每位入镜人物的外貌(阶段 3 的人物卡)：按本镜景别裁成一句简述写进 Pa2。
    cast_looks: Mapping[str, str] | None = None
    # 构图：主体在画面里的位置与前中后景安排(见 shot-design-master 构图速查)。
    composition: str = ""
    # 所选视频模型是否音画同生；不出声的模型不写任何声音描述，对白与音效走后期。
    native_audio: bool = True
    # 本镜是否规划了配乐 / 旁白：规划了就不把它们写进排除项。
    music_planned: bool = False
    narration_planned: bool = False


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


def bridge_line(camera_movement: str, end_state: str) -> str:
    """首帧怎么走到尾帧：运镜与动作是桥，不换机位高度、不换光源、不换人物与道具。"""
    move = str(camera_movement or "").strip() or "固定机位"
    landing = str(end_state or "").strip().rstrip("。")
    return (
        f"以所给尾帧结束：首帧到尾帧不换机位高度、不换光源、不换人物与道具，变化只由运镜（{move}）与动作"
        + (f"（走到“{landing}”）" if landing else "")
        + "完成，尾帧构图在最后一帧完整落定，不提前出现、不中途跳变"
    )


# 道具归属：谁拿着、谁穿着、谁身上的——「车钩」句，动作、起始状态和调度里写了谁和它在一个分句里就算谁的。
_HOLD_VERBS = prompt_data.words(_DATA, "hold_verbs")


_IN_HAND = prompt_data.pattern(_DATA, "in_hand")


def prop_holders(props: Sequence[str], characters: Sequence[str], *texts: str) -> list[str]:
    """每件道具写成「道具：某人持有」；文字里找不到归属的只写名字，不替它编一个主人。

    「林夏坐在桌前，录音笔在右手」——拿着的人写在前一个分句里，同一句话里最近提到的人就是他。
    """
    names = sorted({str(name).strip() for name in characters if str(name).strip()}, key=len, reverse=True)
    holders: dict[str, str] = {}
    for text in texts:
        for sentence in re.split(r"[。！？!?\n]", str(text or "")):
            last = ""
            for clause in re.split(r"[，,；;]", sentence):
                named = next((name for name in names if name in clause), "")
                last = named or last
                if not last:
                    continue
                for prop in props:
                    prop = str(prop).strip()
                    if prop and prop not in holders and prop in clause and (
                        any(verb in clause for verb in _HOLD_VERBS) or _IN_HAND.search(clause)
                    ):
                        holders[prop] = last
    return [f"{prop}：{holders[prop]}持有" if prop in holders else prop for prop in (str(item).strip() for item in props) if prop]


def _lock_lines(shot: ShotPromptInput) -> str:
    props = _join(prop_holders(shot.props, shot.characters, shot.start_state, shot.subject_action, shot.blocking)) or "无关键道具"
    cast = _join(shot.characters) or "本镜人物"
    values = {
        "space": f"{shot.scene}；{shot.blocking}",
        "state": f"{cast}：{shot.start_state}" + (f"；视线：{shot.eyeline}" if shot.eyeline else ""),
        "props": props,
        "light": shot.lighting or "延续上一镜主光方向、色温与光比",
        # 声音锁只锁环境铺底；接触音效绑在具体动作上，写在声音设计里。
        "sound": "、".join(split_cues(shot.sound)[0]) or "延续上一镜环境底噪",
    }
    return "\n".join(f"{tag}{values[key]}" for key, tag in _LOCK_TAGS if shot.native_audio or key != "sound")


def _closing_line(sentence: str) -> str:
    """收尾句里的「无字幕」换成写清楚的那句：原有招牌留着，叠加的字幕水印不要。"""
    parts = [part for part in re.split(r"[；;]", sentence.rstrip("。")) if part.strip() and not re.search(r"字幕|水印", part)]
    return "；".join([*parts, SIGNAGE_RULE.rstrip("。")]) + "。"


def _silent_closing(sentence: str) -> str:
    """收尾句去掉声音相关的分句，只留字幕、水印这类画面要求。"""
    kept = [part for part in re.split(r"[；;]", sentence.rstrip("。")) if part.strip() and not re.search(r"音|BGM|配乐", part)]
    return "；".join(kept) + "。" if kept else ""


def _stage_section(shot: ShotPromptInput) -> str:
    """导演台占位：空间锚、视线锁已经一字不差写过的那句不再重复。"""
    lines = clip_brief.not_restated(list(shot.stage_lines), f"{shot.blocking} {shot.eyeline}")
    return "\n".join([clip_brief.title(), *lines]) if lines else ""


def _sound_section(shot: ShotPromptInput) -> str:
    """音画同生的模型：环境铺底 + 绑定可见事件的关键接触音；H3 已有三层，只补接触音。"""
    if not shot.native_audio:
        return ""
    plan = build_sound_events(
        shot.sound, action=shot.subject_action, props=[*shot.props, *shot.prop_refs], shot_size=shot.shot_size,
        dialogue=bool(shot.dialogue.strip()), narration=shot.narration_planned, music=shot.music_planned,
    )
    if shot.sound_layers.strip():
        lines = plan.contact_lines()
        return "【声音事件】" + "\n".join(lines) if lines else ""
    return "【声音设计】" + plan.text


def compile_shot_prompt(
    pack: StylePack, shot: ShotPromptInput, *, model: str, max_duration_seconds: int | None = None,
    distill: Callable[[Mapping[str, str], int], Mapping[str, str] | None] | None = None,
) -> CompiledVideoPrompt:
    """The prompt for one clip, sectioned, then fitted to ``model``'s budget.

    The clip length must be inside the selected model's range, and the space the prompt
    describes must be restated in full — a clip prompt cannot say "same as above" about a
    batch the model never saw.
    """
    if is_no_line(shot.dialogue):
        shot = replace(shot, dialogue="")
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
        # 首尾帧之间要有一条走得通的路(《首尾帧衔接》)：两帧不跨机位、不跨光源、不跨人物道具，
        # 中间的变化只由本镜的运镜和动作完成，尾帧在最后一帧落定，不提前出现、不中途跳变。
        structure.append(bridge_line(shot.camera_movement, shot.end_state))
    if cut_label:
        structure.append(f"切入本镜：{cut_label}")
    anchors = [note.strip().rstrip("。") + "。" for note in shot.reference_notes if str(note).strip()]
    timeline = f"{shot.carry_in}{shot.subject_action}".strip()
    camera = f"景别：{shot.shot_size}；运镜：{shot.camera_movement}"
    dialogue_label = "台词（逐字保持原文，口型同步）" if shot.native_audio else "台词口型（逐字对应原文，只做口型）"
    dialogue = (
        f"{dialogue_label}：{format_dialogue(shot.dialogue, shot.characters, action=shot.subject_action, on_screen=shot.characters)}"
        if shot.dialogue.strip() else "无台词，人物闭口。"
    )
    end_state = f"落幅：{shot.end_state}"
    # 打戏镜头多一条打斗铁律：拳拳到肉、飘逸流畅、连贯不断档；文戏镜头换成动作顺序铁律：按写明的先后一步一步做。
    rule_ids = [
        "physics", "form", "fight" if "fight" in situations else "action_chain",
        *(["lip_sync"] if shot.dialogue.strip() else []),
    ]
    rules = iron_rules(pack, subjects=list(shot.characters), reference_kinds=list(shot.reference_kinds), rule_ids=rule_ids)
    rules.extend(str(item).strip() for item in shot.continuity_constants if str(item).strip())

    sections: dict[str, str] = {
        **_asset_anchor_sections(shot),
        "anchors": ("【参考素材职责】\n" + "\n".join(anchors)) if anchors else "",
        "structure": "【结构声明】" + " + ".join(structure) + "。",
        "style_lock": style_lock_block(pack, shot.tone),
        "appearance": appearance_lines(shot.cast_looks or {}, shot.characters, shot.shot_size),
        "quality": pack.quality.strip(),
        "locks": _lock_lines(shot),
        "stage": _stage_section(shot),
        "camera": camera,
        "subject": f"画面：{timeline.rstrip('。')}。",
        "motion": shot.motion_prompt.strip(),
        "expression": f"表演：{shot.expression.strip()}" if shot.expression.strip() else "",
        "composition": f"构图：{shot.composition.strip()}" if shot.composition.strip() else "",
        "environment": f"背景：{shot.environment.strip()}" if shot.environment.strip() else "",
        "colour": "\n".join(line.strip() for line in shot.palette_lines if str(line).strip()),
        "effects": f"特效：{_join(shot.effects)}" if _join(shot.effects) else "",
        "contact": contact_line(shot.subject_action, [*shot.props, *shot.prop_refs]),
        "handoff": handoff_line(
            shot.subject_action, shot.characters, props=[*shot.props, *shot.prop_refs],
            setting=f"{shot.scene} {shot.blocking}",
        ),
        "dialogue": dialogue,
        "dialogue_notes": f"台词表达：{shot.dialogue_notes.strip()}" if shot.dialogue_notes.strip() and shot.dialogue.strip() else "",
        "end_state": end_state,
        "sound_layers": f"【声音设计·三层】{shot.sound_layers.strip()}" if shot.sound_layers.strip() and shot.native_audio else "",
        "sound": _sound_section(shot),
        "closing": _closing_line(pack.sound.closing_sentence if shot.native_audio else _silent_closing(pack.sound.closing_sentence)),
        "rules": "【关键约束】\n" + "\n".join(rules),
        "negatives": " + ".join(negatives),
    }
    names = [*shot.cast_refs, *shot.scene_refs, *shot.prop_refs]
    for key in _MARKED_SECTIONS:
        if sections.get(key):
            sections[key] = mark_mentions(sections[key], names)
    # 重复和占位话任何模型都不发。超预算时有精炼器就精炼(内容不丢)，没有才逐段裁剪。
    kept, report = prompt_budget.compress(dedupe(sections), model, distill=distill)
    text = _render(kept)
    report.total_length = prompt_budget.prompt_length(text)
    return CompiledVideoPrompt(text=text, sections=kept, pressure=report, style_pack=pack.id, negatives=negatives)


# Pa1：锚点、结构、锁、镜头块；Pa2：风格锁、外貌、画质、声音；Pa3：铁律与负向词。
_ORDER = (
    "anchor_cast", "anchor_costumes", "anchor_scene", "anchor_props", "anchors", "structure", "locks", "stage", "camera",
    "composition", "subject", "motion", "expression", "environment",
    "colour", "effects", "contact", "handoff", "dialogue", "dialogue_notes", "end_state",
    "style_lock", "appearance", "quality", "sound_layers", "sound", "closing",
    "rules", "negatives",
)
_BLANK_BEFORE = frozenset({"structure", "locks", "stage", "camera", "style_lock", "sound_layers", "sound", "rules"})
# 正文里出现资产名字就标成 @[名字] 的小节；风格锁、素材职责、铁律和负面词不标。
_MARKED_SECTIONS = (
    "locks", "stage", "camera", "composition", "subject", "motion", "expression", "environment", "effects", "contact",
    "handoff", "dialogue", "dialogue_notes", "end_state",
)


# Verbs that put a prop in someone's hand, and the kind of contact each one asks for.
_SUPPORT_VERBS = prompt_data.words(_DATA, "support_verbs")
_REST_VERBS = prompt_data.words(_DATA, "rest_verbs")
_GRIP_VERBS = prompt_data.words(_DATA, "grip_verbs")


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


# 人物之间递交物件的动作：模型最容易让手或物件穿过柜台、玻璃和门。
_HANDOFF_VERBS = prompt_data.words(_DATA, "handoff_verbs")
# 台面类可以隔着递（店员与顾客隔柜台）；封闭类一旦夹在两人之间，手就只能穿过去。
_OPEN_SURFACES = prompt_data.words(_DATA, "open_surfaces")
_SEALED_BARRIERS = prompt_data.words(_DATA, "sealed_barriers")


def handoff_line(action: str, characters: Sequence[str], *, props: Sequence[str] = (), setting: str = "") -> str:
    """两人之间递、接物件时写清一条走得通的路径：同处一个空间、物件在手够得着的地方、封闭隔挡只在背景。"""
    action = str(action or "")
    if not any(verb in action for verb in _HANDOFF_VERBS):
        return ""
    cast = [str(name).strip() for name in characters if str(name).strip()]
    named = [name for name in cast if name in action]
    pair = (named if len(named) >= 2 else list(dict.fromkeys([*named, *cast])))[:2]
    if len(pair) < 2:
        return ""
    clause = next((part for part in re.split(r"[，,。；;]", action) if any(verb in part for verb in _HANDOFF_VERBS)), action)
    names = [str(prop).strip() for prop in props if str(prop).strip()]
    item = next((name for name in names if name in clause), next((name for name in names if name in action), "物件"))
    context = f"{setting}{action}"
    surface = next((word for word in _OPEN_SURFACES if word in context), "")
    sealed = [word for word in _SEALED_BARRIERS if word in context][:2]
    if surface:
        where = f"同在一个空间里，中间只隔一张开放的{surface}，台面上方无遮挡"
    elif not sealed:
        where = "之间没有遮挡"
    else:
        where = "同在一个空间里"
    behind = f"；{'、'.join(sealed)}只在背景，不在两人之间，也不在手与{item}之间" if sealed else ""
    return (
        f"递接路径：{pair[0]}与{pair[1]}{where}、相距约一臂；{item}在两人伸手可及处，"
        f"从一只手直接交到另一只手，手臂与{item}只经过两人之间的开阔处{behind}。"
    )


def _asset_anchor_sections(shot: ShotPromptInput) -> dict[str, str]:
    """锚点行：本镜锁定的人物、场景、道具，各自以 @[名字] 列出，写明锁什么、放开什么。"""
    def names(items: Sequence[str]) -> str:
        return "、".join(mention(str(item).strip()) for item in dict.fromkeys(items) if str(item).strip())

    cast, scenes, props = names(shot.cast_refs), names(shot.scene_refs), names(shot.prop_refs)
    people = [str(item).strip() for item in dict.fromkeys(shot.cast_refs) if str(item).strip()]
    # 同一人 / 相异声明：几个人就是几个人，各自只出现一次；一个人的几张参考图是同一个人，不是分身。
    distinct = (
        f"{'、'.join(mention(name) for name in people)}是{len(people)}个不同的人，互不相像，各自在画面里只出现一次；"
        if len(people) >= 2 else "画面里只有这一个人，只出现一次；"
    ) + "同一人物的多张参考图属于同一个人。"
    costumes = "；".join(
        f"{mention(str(wearer).strip())}全程穿{mention(str(costume).strip())}"
        for wearer, costume in dict.fromkeys((str(w), str(c)) for w, c in shot.costume_refs) if str(wearer).strip() and str(costume).strip()
    )
    return {
        "anchor_cast": (
            f"【人物锚点·锁脸】{cast}。脸型、发型、服装与体型以参考图为准，"
            f"只随剧情改变表情、姿态与动作，情绪前后连贯。{distinct}"
        ) if cast else "",
        "anchor_costumes": f"【服装绑定】{costumes}，款式、颜色与配饰以参考图为准，不换装、不增减配饰。" if costumes else "",
        "anchor_scene": (
            f"【场景锚点·锁场景】{scenes}。灯光色调、空间布局与环境动态保持一致；"
            "换到新场景时先交代它的主光方向与空间。"
        ) if scenes else "",
        "anchor_props": f"【道具锚点】{props}。外形、材质、颜色与持有关系保持一致。" if props else "",
    }


# 外貌简述一人最多这么长：Pa2 要的是「角色A 〈外貌简述〉」，长相的细节由参考图锁，不靠文字堆。
APPEARANCE_LIMIT = prompt_data.number(_DATA, "appearance_limit")
_LAYER_LABEL = prompt_data.pattern(_DATA, "layer_label")
# 人物卡的身份锚点里常带戏份和名字(男主角/沈无咎（自称奴才）)、还有「基础身份DNA见陈-04-甲」这类内部引用：
# 都不是长相，模型也不该念出来。
_NOT_A_LOOK = prompt_data.pattern(_DATA, "not_a_look")


def appearance_brief(look: str, shot_size: str, *, name: str = "", limit: int = APPEARANCE_LIMIT) -> str:
    """一位人物的外貌简述：人物卡按本镜景别只留看得见的层，去掉名字与戏份，再逐项凑到 ``limit`` 字。"""
    text = re.sub(r"\s+", " ", str(look or "")).strip().rstrip("。；;")
    if not text:
        return ""
    card = parse_face_card(text)
    if card.has_face_layers:
        text = render_face_card(card, framing_for_shot_size(shot_size)).rstrip("。；;")
    kept: list[list[str]] = []
    length = 0
    for clause in re.split(r"[；;。]", text):
        # 人物卡渲染出来带层名(骨相：…)；简述只要内容，层是给质检看的。
        items = [item.strip() for item in _LAYER_LABEL.sub("", clause.strip()).split("、")]
        items = [item for item in items if item and not _NOT_A_LOOK.search(item) and not (name and name in item)]
        group: list[str] = []
        for item in items:
            extra = len(item) + (1 if group or kept else 0)
            if kept and length + extra > limit:
                return "；".join("、".join(part) for part in [*kept, group] if part)
            group.append(item)
            length += extra
        if group:
            kept.append(group)
    return "；".join("、".join(part) for part in kept)


def appearance_lines(looks: Mapping[str, str], characters: Sequence[str], shot_size: str) -> str:
    """Pa2 的人物外貌段：本镜每位人物一句，没有人物卡的人不写。"""
    lines = []
    for name in dict.fromkeys(str(item).strip() for item in characters if str(item).strip()):
        brief = appearance_brief(str(looks.get(name) or ""), shot_size, name=name)
        if brief:
            lines.append(f"{mention(name)}：{brief}。")
    return ("人物外貌：" + "".join(lines)) if lines else ""


# 这些分句本身就是"说话"，不能当作开口前的动作；台词原文接在动作后面时到此为止。
_SPEECH_CLAUSE = prompt_data.words(_DATA, "speech_clause")
_LINES_START = prompt_data.words(_DATA, "lines_start")
# 分镜表的画面描述大半在写构图和光，这些分句不是人在做的动作，写成「某人先无多余手指」只会让模型困惑。
_NOT_AN_ACTION = prompt_data.pattern(_DATA, "not_an_action")
_LONGEST_LEAD = prompt_data.number(_DATA, "longest_lead")


def _lead_actions(action: str, names: Sequence[str]) -> dict[str, str]:
    """每个人开口前最后做的那个可见动作，只认以他的名字开头的分句。

    分镜表的画面描述大半在写构图、光和身体状态，没写名字的分句分不清是不是这个人在做事；
    宁可不写，也不写成「某人先无多余手指，随后开口」。
    """
    leads: dict[str, str] = {}
    for clause in re.split(r"[，,。；;！？!?\n]", str(action or "")):
        clause = clause.strip()
        if any(mark in clause for mark in _LINES_START):
            break
        name = next((name for name in names if clause.startswith(name)), "")
        body = clause[len(name):].strip()
        if (
            name and body and len(body) <= _LONGEST_LEAD
            and not any(word in clause for word in _SPEECH_CLAUSE) and not _NOT_AN_ACTION.search(body)
            and not any(other in body for other in names if other != name)
        ):
            leads[name] = body
    return leads


_OTHER_SPEAKER = prompt_data.pattern(_DATA, "other_speaker", re.S)


def format_dialogue(
    dialogue: str, speakers: Sequence[str], *, action: str = "", on_screen: Sequence[str] = (),
) -> str:
    """台词逐行写成 ``@[说话人]{台词}``；认不出说话人的行(旁白、画外音)只用花括号括起原文。

    给了 ``action`` 时，说话人先做开口前的那个动作再开口；给了 ``on_screen`` 时，末尾写明
    只有谁在说话、画面里其他人闭口不出声——多人同框时模型最容易把台词安到别人嘴上。
    """
    known = sorted({str(name).strip() for name in speakers if str(name).strip()}, key=len, reverse=True)
    leads = _lead_actions(action, known) if action else {}
    lines: list[str] = []
    spoken: list[str] = []
    others: list[str] = []  # 开口的人不在本镜人物名单里：也算在说话，只是没有参考图可标
    for line in dialogue_segments(dialogue):
        if is_no_line(line):
            continue
        for name in known:
            # 「姜照：……」或「姜照（平静）：……」——语气写在说话人后面、台词的花括号外面。
            matched = re.match(re.escape(name) + r"\s*(?:[（(]([^）)]*)[）)])?\s*[：:]\s*(.*)$", line, re.S)
            if matched:
                notes, speech = split_speech(matched.group(2))
                delivery = "".join(f"（{note}）" for note in [*filter(None, [matched.group(1)]), *notes])
                lead = f"{mention(name)}先{leads[name]}，随后" if name in leads and name not in spoken else ""
                lines.append(f"{lead}{mention(name)}{delivery}{speech}")
                spoken.append(name)
                break
        else:
            # 不在本镜人物里的说话人(旁白、画外的人)：名字写在花括号外面，不然会被当成台词念出来。
            labelled = _OTHER_SPEAKER.match(line)
            if labelled:
                notes, speech = split_speech(labelled.group(3))
                delivery = "".join(f"（{note}）" for note in [*filter(None, [labelled.group(2)]), *notes])
                lines.append(f"{labelled.group(1)}{delivery}{speech}")
                if not is_narrator(labelled.group(1)):
                    others.append(labelled.group(1))
            elif re.search(r"[{｛「『“]", line):
                notes, speech = split_speech(line)
                lines.append("".join(f"（{note}）" for note in notes) + speech)
            else:
                lines.append(f"{{{line}}}")
    text = " ".join(lines)
    cast = list(dict.fromkeys(str(name).strip() for name in on_screen if str(name).strip()))
    if not cast or not lines:
        return text
    talkers = list(dict.fromkeys(spoken))
    silent = "、".join(mention(name) for name in cast if name not in talkers)
    named = [mention(name) for name in talkers] + list(dict.fromkeys(others))
    if not named:
        return f"{text}（画外声，画面人物闭口不出声）"
    only = f"只有{'、'.join(named)}说话"
    if len(named) > 1:
        only += "，按台词顺序轮流开口，同一时刻只有一人出声"
    return f"{text}（{only}{f'；{silent}闭口不出声' if silent else ''}）"


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


def extension_prompt(
    pack: StylePack, *, source_ref: str, seconds: int, continuation: str, mask: str = "",
    key_light: str = "", space_snapshot: str = "", chain_index: int = 0,
) -> str:
    """The prompt that extends a generated clip: continuity first, the look restated last.

    ``key_light`` names the real light (主光方向 + 色温) rather than "光线不变"; ``space_snapshot``
    is restated only on the chain positions :func:`space_restatement` picks (``chain_index`` is 1-based).
    """
    parts = [
        f"参考{source_ref}的内容，延长视频{seconds}s向后延长。要求延长自然、动作衔接流畅，禁止生硬切镜、禁止物体凭空出现。",
        continuation.strip(),
    ]
    if key_light.strip():
        parts.append(f"光线：主光{key_light.strip()}，延长片段内主光方向与色温不变。")
    if space_snapshot.strip() and chain_index and space_restatement(chain_index) != "same":
        parts.append(f"【空间快照】{space_snapshot.strip()}")
    if mask.strip():
        parts.append(
            f"需要在切镜处使用“遮罩转场”：{mask.strip()}完全遮挡镜头使画面变暗，随后镜头穿过{mask.strip()}拉开，直接显现出下一个场景。"
        )
    parts.append(pack.extension_restatement)
    parts.append(pack.sound.closing_sentence)
    return "\n".join(part for part in parts if part)


__all__ = [
    "CompiledVideoPrompt", "ShotPromptInput", "bridge_line", "compile_shot_prompt", "extension_prompt", "format_dialogue", "handoff_line",
]
