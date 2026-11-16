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

The three paragraphs open with the literal headers ``Pa1`` / ``Pa2`` / ``Pa3`` and carry the
fixed sentences of 《系统实际下发提示词骨架》 (:mod:`app.core.clip_skeleton`): 锚型定义 and the
same-person line in Pa1, the dialogue language before the shot sequence (``2 Conti Movs：``),
the fixed space axis and the fight camera / impact-sound lines in Pa2, and in Pa3 the
performance lock, the round lock, the voice and text bans, then portrait safety, the on-screen
text policy and the ban list.

The budget applies to the body: the style lock, anchors, rules, negatives, the closing
sentence and the skeleton's fixed sentences are restated on every prompt and are not measured. The optional body sections
(sound layers, environment detail, colour, effects, delivery notes) are cut in that order
when the body is over the target model's budget; the locks, the subject, the action, the
camera and the dialogue never are. The result carries a pressure report so the shot
workspace can show what was cut.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace

from app.core import character_locks, clip_skeleton, prompt_budget, prompt_data
from app.core.asset_mentions import mark_mentions, mention
from app.core.face_card import framing_for_shot_size, parse_face_card, render_face_card
from app.core.prompt_distiller import dedupe, is_no_line
from app.core.screenwriting.speech import is_narrator
from app.core.spatial_stage import clip_brief
from app.core.spatial_stage.models import StagePlan
from app.core.spatial_stage.projection import CameraView
from app.core.spatial_stage.prompting import prompt_landmarks
from app.core.spoken_lines import dialogue_segments, split_speech, spoken_lines
from app.core.sound_events import ContactSound, build_sound_events, split_cues
from app.core.storyboard_director import space_restatement
from app.core.style_packs import SIGNAGE_RULE, StylePack, iron_rules, negatives_for, style_lock_block
from app.core.video_references import MIN_SHOT_SECONDS

logger = logging.getLogger(__name__)

# 词表、标签、句式都是数据(app/data/prompt/clip_prompt.json)：这里只读。
_DATA = "clip_prompt"
_LOCK_TAGS = prompt_data.pairs(_DATA, "lock_tags")
# A clip prompt stands on its own: it may not refer back to a batch the model never saw.
_FORBIDDEN_SHORTHANDS = prompt_data.words(_DATA, "forbidden_shorthands")
# 只认单独成词的省略语：「双手按在合同上」里的「同上」前面是汉字，是别的词的一部分，不算。
_SHORTHAND = re.compile(
    "|".join(prompt_data.text(_DATA, "shorthand_guard") + re.escape(word) for word in sorted(_FORBIDDEN_SHORTHANDS, key=len, reverse=True))
)
# 背对镜头的画面：只演看得见的肩背与站姿。
_BACK_VIEW_WORDS = prompt_data.words(_DATA, "back_view_words")
# 「背对(着/向)林夏」：背对的是另一个人，不是镜头。
_BACK_VIEW_LEAD = prompt_data.pattern(_DATA, "back_view_lead")
# 这个模块自己写的句子、标签、分隔符和分句正则：app/data/prompt/video_prompt_engine.json。
_WORDING = "video_prompt_engine"


def _says(key: str, /, **values: object) -> str:
    """A sentence template of the wording table, filled in (``key`` is positional: a template may name a ``{key}``)."""
    return str(prompt_data.load(_WORDING)["says"][key]).format(**values)


def _word(key: str) -> str:
    """A fixed word, sentence or separator of the wording table."""
    return prompt_data.text(_WORDING, key)


def _pattern(key: str) -> str:
    """A regular expression of the wording table, as text (some are appended to an escaped name)."""
    return str(prompt_data.load(_WORDING)["patterns"][key])


_LIST_SEP = _word("list_sep")
_CLAUSE_SEP = _word("clause_sep")
_FULL_STOP = _word("full_stop")
_SENTENCE_SPLIT = re.compile(_pattern("sentence_split"))
_CLAUSE_SPLIT = re.compile(_pattern("clause_split"))
_SEMICOLON_SPLIT = re.compile(_pattern("semicolon_split"))
_CAPTION_CLAUSE = re.compile(_pattern("caption_clause"))
_SOUND_CLAUSE = re.compile(_pattern("sound_clause"))
_SPEAKER_LABEL = _pattern("speaker_label")
_SPEAKER_LINE = _pattern("speaker_line")
_HANDOFF_CLAUSE_SPLIT = re.compile(_pattern("handoff_clause_split"))
_BRIEF_CLAUSE_SPLIT = re.compile(_pattern("brief_clause_split"))
_LEAD_CLAUSE_SPLIT = re.compile(_pattern("lead_clause_split"))
_QUOTED_LINE = re.compile(_pattern("quoted_line"))


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
    # 每个入镜人物此刻为什么这样演(分镜内容的 subtext，已带「只作动机」的说明)。
    motive: str = ""
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
    # 本镜的动作轴线(运动合同)：写进 Pa2「空间坐标全程固定」。
    action_axis: str = ""
    # 入镜的是登记过的真人演员：不写「均为原创虚构角色」，也不禁真人肖像。
    real_person: bool = False
    # 过审构图(少给正脸近景)。默认关：本项目的镜头要看得清脸。
    portrait_safe: bool = False
    # 有自己一张参考图的服装名(旧项目的服装资产)；妆造画在人物图上的不在这里。
    costume_images: Sequence[str] = ()
    # 情绪在画面里看得见的样子(情绪判读：脸、身体)，写在表情后面「外化为…」；背对镜头时不写，听的人去掉张嘴的那几项。
    expression_reading: str = ""
    # 写在表演最后的个人表情习惯(捏过脸的人)；背对镜头时看不见，不写。
    expression_notes: str = ""
    # 导演台上位置全程不变的布景(家具、建筑、落地的道具)，看得见的、点到名的在前(见 fixed_set_pieces)：Pa1 的固定项一句。
    fixed_items: Sequence[str] = ()
    # 本镜带着有效的导演台白模(静帧或白模视频)：站位与家具位置归白模，场景锚点不再说空间布局。
    desk_layers: bool = False


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
    return _LIST_SEP.join(str(item).strip() for item in items if str(item).strip())


def bridge_line(camera_movement: str, end_state: str) -> str:
    """首帧怎么走到尾帧：运镜与动作是桥，不换机位高度、不换光源、不换人物与道具。"""
    move = str(camera_movement or "").strip() or _word("fixed_camera")
    landing = str(end_state or "").strip().rstrip(_FULL_STOP)
    return _says("bridge", move=move, landing=_says("bridge_landing", landing=landing) if landing else "")


# 道具归属：谁拿着、谁穿着、谁身上的——「车钩」句，动作、起始状态和调度里写了谁和它在一个分句里就算谁的。
_HOLD_VERBS = prompt_data.words(_DATA, "hold_verbs")


_IN_HAND = prompt_data.pattern(_DATA, "in_hand")
# 含「持」却不是拿着的词(「原文台词保持不变」的「保持」)：判断持物前先从分句里去掉。
_HOLD_FALSE = tuple(sorted(prompt_data.words(_WORDING, "hold_verb_false"), key=len, reverse=True))


def prop_holders(props: Sequence[str], characters: Sequence[str], *texts: str) -> list[str]:
    """每件道具写成「道具：某人持有」；文字里找不到归属的只写名字，不替它编一个主人。

    「林夏坐在桌前，录音笔在右手」——拿着的人写在前一个分句里，同一句话里最近提到的人就是他。
    """
    names = sorted({str(name).strip() for name in characters if str(name).strip()}, key=len, reverse=True)
    holders: dict[str, str] = {}
    for text in texts:
        for sentence in _SENTENCE_SPLIT.split(str(text or "")):
            last = ""
            for clause in _CLAUSE_SPLIT.split(sentence):
                named = next((name for name in names if name in clause), "")
                last = named or last
                if not last:
                    continue
                holding = clause
                for word in _HOLD_FALSE:
                    holding = holding.replace(word, "")
                for prop in props:
                    prop = str(prop).strip()
                    if prop and prop not in holders and prop in clause and (
                        any(verb in holding for verb in _HOLD_VERBS) or _IN_HAND.search(holding)
                    ):
                        holders[prop] = last
    return [_says("prop_held", prop=prop, holder=holders[prop]) if prop in holders else prop for prop in (str(item).strip() for item in props) if prop]


def _lock_lines(shot: ShotPromptInput) -> str:
    props = _join(prop_holders(shot.props, shot.characters, shot.start_state, shot.subject_action, shot.blocking)) or _word("no_props")
    cast = _join(shot.characters) or _word("cast_fallback")
    values = {
        "space": _says("lock_space", scene=shot.scene, blocking=shot.blocking),
        "state": _says(
            "lock_state", cast=cast, state=shot.start_state,
            eyeline=_says("lock_eyeline", eyeline=shot.eyeline) if shot.eyeline else "",
        ),
        "props": props,
        "light": shot.lighting or _word("light_fallback"),
        # 声音锁只锁环境铺底；接触音效绑在具体动作上，写在声音设计里。
        "sound": _LIST_SEP.join(split_cues(shot.sound)[0]) or _word("sound_fallback"),
    }
    return "\n".join(f"{tag}{values[key]}" for key, tag in _LOCK_TAGS if shot.native_audio or key != "sound")


def _closing_line(sentence: str) -> str:
    """收尾句里的「无字幕」换成写清楚的那句：原有招牌留着，叠加的字幕水印不要。"""
    parts = [part for part in _SEMICOLON_SPLIT.split(sentence.rstrip(_FULL_STOP)) if part.strip() and not _CAPTION_CLAUSE.search(part)]
    return _CLAUSE_SEP.join([*parts, SIGNAGE_RULE.rstrip(_FULL_STOP)]) + _FULL_STOP


def _silent_closing(sentence: str) -> str:
    """收尾句去掉声音相关的分句，只留字幕、水印这类画面要求。"""
    kept = [part for part in _SEMICOLON_SPLIT.split(sentence.rstrip(_FULL_STOP)) if part.strip() and not _SOUND_CLAUSE.search(part)]
    return _CLAUSE_SEP.join(kept) + _FULL_STOP if kept else ""


def _stage_section(shot: ShotPromptInput) -> str:
    """导演台占位：空间锚、视线锁已经一字不差写过的那句不再重复。"""
    lines = clip_brief.not_restated(list(shot.stage_lines), f"{shot.blocking} {shot.eyeline}")
    return "\n".join([clip_brief.title(), *lines]) if lines else ""


def _sound_section(shot: ShotPromptInput, family: str = "") -> str:
    """音画同生的模型：环境铺底 + 绑定可见事件的关键接触音；H3 已有三层，只补接触音。

    Seedance 的音效写在尖括号里：铺底一对，每个接触音一对；静默规则和人声不括。
    """
    if not shot.native_audio:
        return ""
    plan = build_sound_events(
        shot.sound, action=shot.subject_action, props=[*shot.props, *shot.prop_refs], shot_size=shot.shot_size,
        dialogue=bool(shot.dialogue.strip()), narration=shot.narration_planned, music=shot.music_planned,
    )
    if family == "seedance":
        plan.bed = clip_skeleton.sfx_marks(plan.bed)
        plan.contacts = [ContactSound(contact.event, clip_skeleton.first_sound_marked(contact.sound)) for contact in plan.contacts]
    if shot.sound_layers.strip():
        lines = plan.contact_lines()
        return _word("sound_events_head") + "\n".join(lines) if lines else ""
    return _word("sound_design_head") + plan.text


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
    shot = _without_shorthands(shot)
    situations = list(shot.situations)
    if len(shot.characters) >= 2 and "multi_person" not in situations:
        situations.append("multi_person")
    negatives = negatives_for(pack, situations, shot.extra_negatives)
    cut = dict(shot.cut_in or {})
    cut_label = str(cut.get("label") or "")
    fight = "fight" in situations
    back = back_view(shot)
    listening = listener_shot(shot)
    # A single clip carries no absolute seconds: its length travels as the request's duration. A clip
    # of several moments writes each moment's span in its block head (slice_video, 「7—10秒」, the
    # user's choice): the spans cover 0 to the end with no gap and say which moment comes when.
    structure = [
        _says("structure_single", aspect=shot.aspect_ratio),
        _word("first_frame") if shot.first_frame else _word("no_first_frame"),
    ]
    if shot.last_frame:
        # 首尾帧之间要有一条走得通的路(《首尾帧衔接》)：两帧不跨机位、不跨光源、不跨人物道具，
        # 中间的变化只由本镜的运镜和动作完成，尾帧在最后一帧落定，不提前出现、不中途跳变。
        structure.append(bridge_line(shot.camera_movement, shot.end_state))
    if cut_label:
        structure.append(_says("cut_in", label=cut_label))
        # 切机位不是让人动：换了角度，人物站位与朝向照旧。
        structure.append(prompt_data.text(_DATA, "cut_keeps_blocking"))
    anchors = [note.strip().rstrip(_FULL_STOP) + _FULL_STOP for note in shot.reference_notes if str(note).strip()]
    timeline = f"{shot.carry_in}{shot.subject_action}".strip()
    camera = _CLAUSE_SEP.join(filter(None, (
        _says("camera", size=shot.shot_size, move=shot.camera_movement),
        clip_skeleton.listener_camera(shot.shot_size, shot.camera_movement, listening=listening),
    )))
    dialogue_label = _word("dialogue_label_native") if shot.native_audio else _word("dialogue_label_silent")
    dialogue = (
        _says(
            "dialogue", label=dialogue_label,
            lines=format_dialogue(shot.dialogue, shot.characters, action=shot.subject_action, on_screen=shot.characters),
        )
        if shot.dialogue.strip() else _word("no_dialogue")
    )
    end_state = _says("end_state", end_state=shot.end_state)
    # 打戏镜头多一条打斗铁律：拳拳到肉、飘逸流畅、连贯不断档；文戏镜头换成动作顺序铁律：按写明的先后一步一步做。
    # 背对镜头看不见嘴：不写口型同步。
    rule_ids = [
        "physics", "form", "fight" if fight else "action_chain",
        *(["lip_sync"] if shot.dialogue.strip() and not back else []),
    ]
    rules = iron_rules(pack, subjects=list(shot.characters), reference_kinds=list(shot.reference_kinds), rule_ids=rule_ids)
    rules.extend(str(item).strip() for item in shot.continuity_constants if str(item).strip())
    family = clip_skeleton.family(model)

    sections: dict[str, str] = {
        **_asset_anchor_sections(shot),
        **_skeleton_sections(shot, family, fight=fight, back=back),
        "anchors": _says("anchors", notes="\n".join(anchors)) if anchors else "",
        "structure": _says("structure", items=" + ".join(structure)),
        # 一段只做一个主要变化；没写的动作不加，停顿也可以。写在 Pa1(Pa3 的铁律在 2000 字上限下多半被截掉)；打戏有自己的节奏。
        "one_change": "" if fight else prompt_data.text(_DATA, "one_change") + _FULL_STOP,
        # 固定项和动作项分开写：哪些布景位置全程不变、人物不换位(打戏也写，家具同样不能跳)。Pa1，2000 字截断也留得住。
        "fixed_items": fixed_items_line(shot.fixed_items, people=any(str(name).strip() for name in shot.characters)),
        "style_lock": style_lock_block(pack, shot.tone),
        "appearance": appearance_lines(shot.cast_looks or {}, shot.characters, shot.shot_size),
        "quality": pack.quality.strip(),
        "locks": _lock_lines(shot),
        "stage": _stage_section(shot),
        "camera": camera,
        "subject": _says("subject", timeline=timeline.rstrip(_FULL_STOP)),
        "motion": shot.motion_prompt.strip(),
        "motive": shot.motive.strip(),
        "expression": _expression(shot, back=back, listening=listening),
        "composition": _says("composition", text=shot.composition.strip()) if shot.composition.strip() else "",
        "environment": _says("environment", text=shot.environment.strip()) if shot.environment.strip() else "",
        "colour": "\n".join(line.strip() for line in shot.palette_lines if str(line).strip()),
        "effects": _says("effects", text=_join(shot.effects)) if _join(shot.effects) else "",
        "contact": "".join(filter(None, (
            contact_line(shot.subject_action, [*shot.props, *shot.prop_refs]),
            # 坐进车里、坐上椅子、靠住柱子：身体和物件的接触，道具、车辆、商品和固定陈设都算。
            body_contact_line(shot.subject_action, [*shot.props, *shot.prop_refs, *shot.fixed_items], shot.characters),
        ))),
        "handoff": handoff_line(
            shot.subject_action, shot.characters, props=[*shot.props, *shot.prop_refs],
            setting=f"{shot.scene} {shot.blocking}",
        ),
        "dialogue": dialogue,
        "dialogue_notes": (
            _says("dialogue_notes", text=shot.dialogue_notes.strip()) if shot.dialogue_notes.strip() and shot.dialogue.strip() else ""
        ),
        "end_state": end_state,
        "sound_layers": _says("sound_layers", text=shot.sound_layers.strip()) if shot.sound_layers.strip() and shot.native_audio else "",
        "sound": _sound_section(shot, family),
        "closing": _closing_line(pack.sound.closing_sentence if shot.native_audio else _silent_closing(pack.sound.closing_sentence)),
        "rules": _says("rules", rules="\n".join(rules)),
        "negatives": " + ".join(negatives),
    }
    names = [*shot.cast_refs, *shot.scene_refs, *shot.prop_refs]
    for key in _MARKED_SECTIONS:
        if sections.get(key):
            sections[key] = mark_mentions(sections[key], names)
    # 重复和占位话任何模型都不发。超预算时有精炼器就精炼(内容不丢)，没有才逐段裁剪。
    kept, report = prompt_budget.compress(dedupe(sections), model, fixed=prompt_budget.fixed_for(model) | UNMEASURED, distill=distill)
    text = _render(kept)
    report.total_length = prompt_budget.prompt_length(text)
    return CompiledVideoPrompt(text=text, sections=kept, pressure=report, style_pack=pack.id, negatives=negatives)


_OFF_SCREEN_LABELS = frozenset(word.upper() for word in prompt_data.words(_WORDING, "off_screen_labels"))


def _off_screen_label(note: str | None) -> bool:
    """说话人后面的括注写着画外(「陈默（画外）：」「陈默（OS）：」)。"""
    return str(note or "").strip().upper() in _OFF_SCREEN_LABELS


def dialogue_voices(dialogue: str, characters: Sequence[str]) -> tuple[list[tuple[str, bool]], int]:
    """``([(说话人, 是否在画外), …] 按开口顺序, 台词句数)``；旁白算一句台词，不算一个人。

    认得「名字：」「名字（语气）：」「名字（画外）：」：括注写着画外的人即使在本镜人物里也算画外；
    不在本镜人物里的说话人一律在画外。
    """
    known = sorted({str(name).strip() for name in characters if str(name).strip()}, key=len, reverse=True)
    voices: list[tuple[str, bool]] = []
    turns = 0
    for line in dialogue_segments(dialogue):
        if is_no_line(line):
            continue
        turns += 1
        labelled = _OTHER_SPEAKER.match(line)
        name = next((name for name in known if re.match(re.escape(name) + _SPEAKER_LABEL, line)), "")
        if name:
            note = labelled.group(2) if labelled and labelled.group(1) == name else None
            voices.append((name, _off_screen_label(note)))
        elif labelled and not is_narrator(labelled.group(1)):
            voices.append((labelled.group(1), True))
    return list(dict.fromkeys(voices)), turns


def dialogue_speakers(dialogue: str, characters: Sequence[str]) -> tuple[list[str], list[str], int]:
    """``(画面里开口的人, 画外开口的人, 台词句数)``；旁白算一句台词，不算一个人。"""
    voices, turns = dialogue_voices(dialogue, characters)
    on_screen = [name for name, off in voices if not off]
    off_screen = [name for name, off in voices if off and name not in on_screen]
    return list(dict.fromkeys(on_screen)), list(dict.fromkeys(off_screen)), turns


def _without_shorthands(shot: ShotPromptInput) -> ShotPromptInput:
    """空间、调度、起始状态里的「同上」「同前」这类省略语：模型没看过上一批，删掉并记一笔，不让一镜拖垮整个阶段。

    只认单独成词的(前面不是汉字)：「双手按在合同上」的「同上」不算。
    """
    fields = {"scene": shot.scene, "blocking": shot.blocking, "start_state": shot.start_state}
    found = [match.group(0) for value in fields.values() for match in _SHORTHAND.finditer(str(value or ""))]
    if not found:
        return shot
    logger.warning(
        "shot %s: shorthand %s removed from its space / blocking / start state; restate them in full",
        shot.shot_index, _LIST_SEP.join(dict.fromkeys(found)),
    )
    cleaned = {
        key: re.sub(_pattern("shorthand_gap"), r"\1", _SHORTHAND.sub("", str(value or ""))).strip(_word("shorthand_trim"))
        for key, value in fields.items()
    }
    return replace(shot, **cleaned)


def _picture_text(shot: ShotPromptInput) -> str:
    """看画面是什么样的文字：构图与画面描述(去掉抄进来的台词原文——台词里说「你背后」不是背影)。"""
    action = str(shot.subject_action or "")
    if shot.dialogue.strip():
        action = action.replace(shot.dialogue.strip(), "")
    return f"{shot.composition} {action}"


def back_view(shot: ShotPromptInput) -> bool:
    """这一镜拍的是背面：构图或画面写了背对镜头、背影、背后、背对。

    「背对林夏」「背对着陈默」是背对另一个人，不是背对镜头，不算。
    """
    text = _picture_text(shot)
    others = [str(name).strip() for name in (*shot.characters, *shot.cast_refs) if str(name).strip()]
    for word in _BACK_VIEW_WORDS:
        for match in re.finditer(re.escape(word), text):
            rest = _BACK_VIEW_LEAD.sub("", text[match.end():])
            if not any(rest.startswith(name) for name in others):
                return True
    return False


def listener_shot(shot: ShotPromptInput) -> bool:
    """画面里的人都在听：开口的是画外的人(「陈默（画外）：」、或不在本镜人物里的人)，画面里没有人开口。

    认不出说话人的台词(没有「名字：」)和旁白不算：不知道是谁在说，也就说不上谁在听。
    """
    if not any(str(name).strip() for name in shot.characters):
        return False
    on_screen, off_screen, _turns = dialogue_speakers(shot.dialogue, shot.characters)
    return bool(off_screen) and not on_screen


def _closed_mouth(reading: str) -> str:
    """听的人的情绪判读里去掉张嘴的那几项(「嘴唇微张」)：他闭口不出声。"""
    pieces = re.split(_pattern("reading_split"), str(reading or ""))
    items, seps = pieces[0::2], pieces[1::2]
    out = ""
    for index, item in enumerate(items):
        if not item.strip() or re.search(_pattern("mouth_open"), item):
            continue
        if out:
            out += seps[index - 1]
        out += item
    return out.strip()


def trigger_words(dialogue: str) -> str:
    """听的人等的那一句的最后几个字：最后一句台词的最后一个分句，长了只取末尾几个字。"""
    lines = [line for line in spoken_lines([str(dialogue or "")]) if line.strip()]
    if not lines:
        return ""
    clauses = [part for part in re.split(_pattern("trigger_clause_split"), lines[-1]) if part.strip()]
    if not clauses:
        return ""
    last = clauses[-1].strip()
    most = prompt_data.number(_WORDING, "reaction_words")
    return last if len(last) <= most + prompt_data.number(_WORDING, "reaction_words_slack") else last[-most:]


def _trigger_lead() -> tuple[str, str]:
    """「听到“{words}”之后才…」模板里台词前后的两截字面量，用来在提示词里认出触发句。"""
    template = str(prompt_data.load(_WORDING)["says"]["reaction_after"])
    head, _, tail = template.partition("{words}")
    return head.split("}")[-1], tail.split("{")[0]


def reaction_triggers(sections: Mapping[str, str]) -> set[str]:
    """提示词里写着的反应触发句(「听到“我查不到”之后才」)：精炼时必须原样留着，不然反应又挪回镜头开头。"""
    head, tail = _trigger_lead()
    if not head or not tail:
        return set()
    pattern = re.compile(re.escape(head) + r"[^\n]{1,24}?" + re.escape(tail))
    return {match.group(0) for value in sections.values() for match in pattern.finditer(str(value or ""))}


def _expression(shot: ShotPromptInput, *, back: bool, listening: bool) -> str:
    """表演一节：情绪、它在画面里看得见的样子、个人习惯。

    背对镜头只写肩背、重心与站姿(不写外化的眼神口鼻)，全程不转身；画面里的人在听时，反应写在触发它的那句台词之后，
    此前保持原状，并去掉张嘴的判读。
    """
    reading = "" if back else (_closed_mouth(shot.expression_reading) if listening else str(shot.expression_reading or "").strip())
    text = _CLAUSE_SEP.join(part for part in (
        shot.expression.strip(),
        _says("expression_reading", reading=reading) if reading else "",
        "" if back else shot.expression_notes.strip(),
    ) if part)
    if back:
        text = _says("expression_back", text=text) if text else _says("expression_back_bare")
    words = trigger_words(shot.dialogue) if listening and text else ""
    if words:
        text = _says("reaction_after", words=words, reaction=text)
    return _says("expression", text=text) if text else ""


def _skeleton_sections(shot: ShotPromptInput, family: str, *, fight: bool, back: bool = False) -> dict[str, str]:

    """《系统实际下发提示词骨架》每条都重申的固定句：这一镜该写哪几句(见 clip_skeleton)。"""
    on_screen, off_screen, turns = dialogue_speakers(shot.dialogue, shot.characters)
    references = any(str(name).strip() for name in (*shot.cast_refs, *shot.scene_refs, *shot.prop_refs))
    people = any(str(name).strip() for name in shot.characters)
    camera_fixed = clip_skeleton.fixed_camera(shot.camera_movement)
    return {
        **clip_skeleton.headers(),
        "anchor_types": clip_skeleton.anchor_types(
            shot.cast_refs, shot.scene_refs, shot.prop_refs, shot.costume_refs, shot.costume_images,
        ),
        "same_instance": clip_skeleton.same_instance(
            shot.cast_refs, shot.costume_refs, shot.costume_images, references=references,
        ),
        "dialogue_language": clip_skeleton.dialogue_language(family, on_screen, off_screen) if shot.native_audio and turns else "",
        "space_axis": clip_skeleton.space_axis(shot.action_axis, fight_pair=fight and len(shot.characters) >= 2),
        "lens": clip_skeleton.lens(fight=fight, camera_movement=shot.camera_movement),
        "impact_sound": clip_skeleton.impact_sound(family) if fight and shot.native_audio else "",
        "performance_lock": clip_skeleton.performance_lock(
            family, short=shot.duration_seconds < clip_skeleton.SHORT_SECONDS, script=f"{shot.subject_action}{shot.dialogue}", back=back,
        ) if people else "",
        "chain_lock": clip_skeleton.chain_lock(fight=fight, camera_fixed=camera_fixed, turns=turns),
        "voice_ban": clip_skeleton.voice_ban(native_audio=shot.native_audio),
        **clip_skeleton.tail(
            people=people, real_person=shot.real_person, review_safe=shot.portrait_safe, dialogue=turns > 0,
        ),
    }


# Pa1：锚型与锚点、同一人声明、对白语言、结构、锁、镜头序列；Pa2：风格锁、空间坐标、外貌、画质、声音；
# Pa3：铁律、表演锁、回合锁、禁令与负向词，最后是肖像、画面文字、禁止出现三段。
_ORDER = (
    "pa1", "anchor_types", "anchor_cast", "anchor_costumes", "same_instance", "anchor_scene", "anchor_props", "anchors",
    "dialogue_language", "structure", "one_change", "fixed_items", "locks", "stage",
    "sequence_head", "camera", "composition", "subject", "motion", "motive", "expression", "environment",
    "colour", "effects", "contact", "handoff", "dialogue", "dialogue_notes", "end_state", "end_hold",
    "pa2", "style_lock", "space_axis", "appearance", "quality", "lens", "sound_layers", "sound", "impact_sound", "closing",
    "pa3", "rules", "performance_lock", "chain_lock", "voice_ban", "negatives", "portrait_safety", "text_policy", "ban_list",
)
_BLANK_BEFORE = frozenset({
    "structure", "locks", "stage", "camera", "style_lock", "sound_layers", "sound", "rules",
    *clip_skeleton.HEADERS, "portrait_safety", "text_policy", "ban_list",
})
# 正文里出现资产名字就标成 @[名字] 的小节；风格锁、素材职责、铁律和负面词不标。
_MARKED_SECTIONS = (
    "locks", "stage", "camera", "composition", "subject", "motion", "motive", "expression", "environment", "effects", "contact",
    "handoff", "dialogue", "dialogue_notes", "end_state",
)


#: 每条重申的固定句、但不在骨架(clip_skeleton.SECTIONS)里的小节：同样不计入正文预算。
UNMEASURED: frozenset[str] = frozenset({"fixed_items"})
_FIXED_ITEMS = prompt_data.value(_DATA, "fixed_items")
# 布景看不看得见：中心点在镜头前方、画框之内(含镜头运动的终点)。
_IN_FRONT_M = 0.2


def _seen_by(view: CameraView, landmark) -> bool:
    across, up, depth = view.project((landmark.position[0], landmark.elevation_m + landmark.size[2] / 2, landmark.position[1]))
    return depth > _IN_FRONT_M and abs(across) <= 1.0 and abs(up) <= 1.0


def fixed_set_pieces(
    plan: StagePlan | None, shot_ids: Sequence[object], *, text: str = "", handled: Sequence[str] = (),
) -> tuple[list[str], list[str]]:
    """导演台上位置全程不变的布景：``(看得见或点到名的, 其余)``，各按方案里的顺序。

    布景是家具、建筑和落在地上的道具与灯具(炭盆、落地灯)；有人拿着、搁在别的东西上、或是本镜要拿的道具(``handled``)
    会动，不算。``shot_ids`` 是这一段里的几个镜头：任一镜头的画框里看得见(机位起止都算)，或 ``text`` 里点到名字，就排前面。
    """
    if plan is None:
        return [], []
    moving = {contact.target for contact in plan.contacts if contact.kind in ("hold", "rest")}
    moving |= {str(name).strip() for name in handled if str(name).strip()}
    pieces = [
        item for item in prompt_landmarks(plan)
        if item.name not in moving and (item.kind in ("furniture", "architecture") or item.elevation_m <= 0)
    ]
    views: list[CameraView] = []
    for shot_id in shot_ids:
        try:
            shot = plan.shot(int(shot_id))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        camera = plan.camera(shot.camera_id) if shot is not None else None
        if camera is not None:
            views += [CameraView.of(camera), CameraView.of(camera, end=True)]
    front: list[str] = []
    rest: list[str] = []
    for item in pieces:
        if item.name in front or item.name in rest:
            continue
        seen = (item.name in text) or any(_seen_by(view, item) for view in views)
        (front if seen else rest).append(item.name)
    return front, rest


def fixed_items_line(names: Sequence[str], *, people: bool = True) -> str:
    """固定项一句：「固定：书案、窗、扶手椅位置全程不变，人物不换位。」

    名字按给的顺序写，整句放不下 ``max_chars`` 就不再往后加(句子长短的限制，不是镜头里能有几样东西)；至少写一样。
    """
    names = list(dict.fromkeys(str(name).strip() for name in names if str(name).strip()))
    if not names:
        return ""
    template = str(_FIXED_ITEMS["line" if people else "line_no_people"])
    separator, limit = str(_FIXED_ITEMS["separator"]), int(_FIXED_ITEMS["max_chars"])
    kept = names[:1]
    for name in names[1:]:
        if len(template.format(names=separator.join([*kept, name]))) > limit:
            break
        kept.append(name)
    return template.format(names=separator.join(kept))


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
    # 「原文台词保持不变」的「保持」不是拿着：先去掉这类含「持」的词再认动作。
    for word in _HOLD_FALSE:
        action = action.replace(word, "")
    named = [str(item).strip() for item in props if str(item).strip() and str(item).strip() in action]
    if not named or not any(verb in action for verb in (*_SUPPORT_VERBS, *_REST_VERBS, *_GRIP_VERBS)):
        return ""
    prop = named[0]
    if any(verb in action for verb in _SUPPORT_VERBS):
        how = _says("contact_support", prop=prop)
    elif any(verb in action for verb in _REST_VERBS):
        how = _says("contact_rest", prop=prop)
    else:
        how = _says("contact_grip", prop=prop)
    return _says("contact", how=how)


_BODY_CONTACT = prompt_data.value(_DATA, "body_contact")
_BODY_CLAUSE = re.compile(_pattern("lead_clause_split"))


def body_contact_line(action: str, objects: Sequence[str], characters: Sequence[str] = ()) -> str:
    """人坐进、坐上、骑上、靠住、躺上一件物件时，身体和它怎么接触：不穿进车壁、不陷进座面、不悬空。

    物件是本镜的道具、车辆、商品和固定陈设；动作里同一分句既有这类动词又点到物件名才写。
    一个分句只认一种(按 order 的先后)，整句最多 max_clauses 条；分句里点到名的人写名字，没点到写「人」。
    """
    names = sorted({str(item).strip() for item in objects if str(item).strip()}, key=len, reverse=True)
    if not names:
        return ""
    verbs = _BODY_CONTACT["verbs"]
    found: list[str] = []
    for clause in _BODY_CLAUSE.split(str(action or "")):
        item = next((name for name in names if name in clause), "")
        how = next((kind for kind in _BODY_CONTACT["order"] if any(verb in clause for verb in verbs[kind])), "") if item else ""
        if how:
            who = next((str(name).strip() for name in characters if str(name).strip() and str(name).strip() in clause), _word("body_someone"))
            found.append(_says(
                "body_inside" if how == "inside" else "body_ride" if how == "ride" else "body_lie" if how == "lie"
                else "body_lean" if how == "lean" else "body_seat",
                item=item, who=who,
            ))
    found = list(dict.fromkeys(found))[: int(_BODY_CONTACT["max_clauses"])]
    return _says("body_contact", how=_CLAUSE_SEP.join(found)) if found else ""


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
    clause = next((part for part in _HANDOFF_CLAUSE_SPLIT.split(action) if any(verb in part for verb in _HANDOFF_VERBS)), action)
    names = [str(prop).strip() for prop in props if str(prop).strip()]
    item = next((name for name in names if name in clause), next((name for name in names if name in action), _word("handoff_item")))
    context = f"{setting}{action}"
    surface = next((word for word in _OPEN_SURFACES if word in context), "")
    sealed = [word for word in _SEALED_BARRIERS if word in context][:2]
    if surface:
        where = _says("handoff_open", surface=surface)
    elif not sealed:
        where = _word("handoff_clear")
    else:
        where = _word("handoff_same_room")
    behind = _says("handoff_behind", barriers=_LIST_SEP.join(sealed), item=item) if sealed else ""
    return _says("handoff", a=pair[0], b=pair[1], where=where, item=item, behind=behind)


def _asset_anchor_sections(shot: ShotPromptInput) -> dict[str, str]:
    """锚点行：本镜锁定的人物、场景、道具，各自以 @[名字] 列出，写明锁什么、放开什么。"""
    def names(items: Sequence[str]) -> str:
        return _LIST_SEP.join(mention(str(item).strip()) for item in dict.fromkeys(items) if str(item).strip())

    cast, scenes, props = names(shot.cast_refs), names(shot.scene_refs), names(shot.prop_refs)
    people = [str(item).strip() for item in dict.fromkeys(shot.cast_refs) if str(item).strip()]
    # 同一人 / 相异声明：几个人就是几个人，各自只出现一次；一个人的几张参考图是同一个人，不是分身。
    distinct = (
        _says("distinct_many", names=_LIST_SEP.join(mention(name) for name in people), count=len(people))
        if len(people) >= 2 else _word("distinct_one")
    ) + _word("same_person")
    costumes = _CLAUSE_SEP.join(
        _says("costume_pair", wearer=mention(str(wearer).strip()), costume=mention(str(costume).strip()))
        for wearer, costume in dict.fromkeys((str(w), str(c)) for w, c in shot.costume_refs) if str(wearer).strip() and str(costume).strip()
    )
    return {
        "anchor_cast": _says("anchor_cast", cast=cast, distinct=distinct) if cast else "",
        "anchor_costumes": _says("anchor_costumes", costumes=costumes) if costumes else "",
        "anchor_scene": (
            # 带着导演台白模时场景锚点不说空间布局(句子在 scene_views.json，与场地图那句同一处)。
            (prompt_data.text("scene_views", "anchor_scene_desk").format(scenes=scenes) if shot.desk_layers else _says("anchor_scene", scenes=scenes))
            if scenes else ""
        ),
        "anchor_props": _says("anchor_props", props=props) if props else "",
    }


# 外貌简述一人最多这么长：Pa2 要的是「角色A 〈外貌简述〉」，长相的细节由参考图锁，不靠文字堆。
APPEARANCE_LIMIT = prompt_data.number(_DATA, "appearance_limit")
_LAYER_LABEL = prompt_data.pattern(_DATA, "layer_label")
# 人物卡的身份锚点里常带戏份和名字(男主角/沈无咎（自称奴才）)、还有「基础身份DNA见陈-04-甲」这类内部引用：
# 都不是长相，模型也不该念出来。
_NOT_A_LOOK = prompt_data.pattern(_DATA, "not_a_look")


def appearance_brief(look: str, shot_size: str, *, name: str = "", limit: int = APPEARANCE_LIMIT) -> str:
    """一位人物的外貌简述：人物卡按本镜景别只留看得见的层，去掉名字与戏份，再逐项凑到 ``limit`` 字。"""
    text = re.sub(r"\s+", " ", str(look or "")).strip().rstrip(_word("brief_trim"))
    if not text:
        return ""
    card = parse_face_card(text)
    if card.has_face_layers:
        text = render_face_card(card, framing_for_shot_size(shot_size)).rstrip(_word("brief_trim"))
    kept: list[list[str]] = []
    length = 0
    for clause in _BRIEF_CLAUSE_SPLIT.split(text):
        # 人物卡渲染出来带层名(骨相：…)；简述只要内容，层是给质检看的。
        items = [item.strip() for item in _LAYER_LABEL.sub("", clause.strip()).split(_LIST_SEP)]
        items = [item for item in items if item and not _NOT_A_LOOK.search(item) and not (name and name in item)]
        group: list[str] = []
        for item in items:
            extra = len(item) + (1 if group or kept else 0)
            if kept and length + extra > limit:
                return _CLAUSE_SEP.join(_LIST_SEP.join(part) for part in [*kept, group] if part)
            group.append(item)
            length += extra
        if group:
            kept.append(group)
    return _CLAUSE_SEP.join(_LIST_SEP.join(part) for part in kept)


def appearance_lines(looks: Mapping[str, str], characters: Sequence[str], shot_size: str) -> str:
    """Pa2 的人物外貌段：本镜每位人物一句，没有人物卡的人不写。"""
    lines = []
    for name in dict.fromkeys(str(item).strip() for item in characters if str(item).strip()):
        # 禁用项(剑始终在右手、战袍不变色)单列在外貌后面：外貌会按字数截短，这几条不能被截掉。
        look, _written = character_locks.split_locks(str(looks.get(name) or ""))
        brief = appearance_brief(look, shot_size, name=name)
        locks = character_locks.lock_line(character_locks.locks_of(str(looks.get(name) or "")))
        if brief or locks:
            lines.append(_says("appearance_line", name=mention(name), look=_CLAUSE_SEP.join(part for part in (brief, locks) if part)))
    return _says("appearance", lines="".join(lines)) if lines else ""


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
    for clause in _LEAD_CLAUSE_SPLIT.split(str(action or "")):
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
            matched = re.match(re.escape(name) + _SPEAKER_LINE, line, re.S)
            if matched:
                notes, speech = split_speech(matched.group(2))
                delivery = "".join(_says("delivery_note", note=note) for note in [*filter(None, [matched.group(1)]), *notes])
                lead = _says("lead", name=mention(name), action=leads[name]) if name in leads and name not in spoken else ""
                lines.append(f"{lead}{mention(name)}{delivery}{speech}")
                spoken.append(name)
                break
        else:
            # 不在本镜人物里的说话人(旁白、画外的人)：名字写在花括号外面，不然会被当成台词念出来。
            labelled = _OTHER_SPEAKER.match(line)
            if labelled:
                notes, speech = split_speech(labelled.group(3))
                delivery = "".join(_says("delivery_note", note=note) for note in [*filter(None, [labelled.group(2)]), *notes])
                lines.append(f"{labelled.group(1)}{delivery}{speech}")
                if not is_narrator(labelled.group(1)):
                    others.append(labelled.group(1))
            elif _QUOTED_LINE.search(line):
                notes, speech = split_speech(line)
                lines.append("".join(_says("delivery_note", note=note) for note in notes) + speech)
            else:
                lines.append(f"{{{line}}}")
    text = " ".join(lines)
    cast = list(dict.fromkeys(str(name).strip() for name in on_screen if str(name).strip()))
    if not cast or not lines:
        return text
    talkers = list(dict.fromkeys(spoken))
    silent = _LIST_SEP.join(mention(name) for name in cast if name not in talkers)
    named = [mention(name) for name in talkers] + list(dict.fromkeys(others))
    if not named:
        return _says("off_screen_only", text=text)
    only = _says("only_speaker", names=_LIST_SEP.join(named))
    if len(named) > 1:
        only += _word("turn_taking")
    # 画外开口的人不出现在画面里(「陈默（画外）：」，或不在本镜人物里的人)。
    _on, away, _turns = dialogue_speakers(dialogue, cast)
    absent = _says("off_screen_absent", names=_LIST_SEP.join(mention(name) if name in cast else name for name in away)) if away else ""
    return _says(
        "speaker_note", text=text, only=only, silent=(_says("silent_cast", names=silent) if silent else "") + absent,
    )


def _render(sections: Mapping[str, str]) -> str:
    lines: list[str] = []
    after_header = False
    for key in _ORDER:
        value = str(sections.get(key) or "").strip()
        if not value:
            continue
        # 段名(Pa1 / Pa2 / Pa3、2 Conti Movs：)前空一行，段名下面紧跟正文。
        if key in _BLANK_BEFORE and lines and not after_header:
            lines.append("")
        lines.append(value)
        after_header = key in clip_skeleton.HEADERS
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
        _says("extend", source=source_ref, seconds=seconds),
        continuation.strip(),
    ]
    if key_light.strip():
        parts.append(_says("extend_light", light=key_light.strip()))
    if space_snapshot.strip() and chain_index and space_restatement(chain_index) != "same":
        parts.append(_says("extend_space", snapshot=space_snapshot.strip()))
    if mask.strip():
        parts.append(_says("extend_mask", mask=mask.strip()))
    parts.append(pack.extension_restatement)
    parts.append(pack.sound.closing_sentence)
    return "\n".join(part for part in parts if part)


__all__ = [
    "CompiledVideoPrompt", "ShotPromptInput", "back_view", "bridge_line", "compile_shot_prompt", "dialogue_speakers", "dialogue_voices",
    "extension_prompt", "format_dialogue", "handoff_line", "listener_shot", "reaction_triggers", "trigger_words",
]
