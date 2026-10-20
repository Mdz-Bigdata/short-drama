# -*- coding: utf-8 -*-
"""One emotion word, everything it implies: face, body, voice and how hard the moment hits.

A screenplay marks a line's emotion once (the shot plan's ``delivery`` note, a
parenthetical in the line, the shot description). The same word has to move the
face and the body in the picture, the voice's pace and pitch, and say whether the
moment is a hit. This table is the single place that says what each word means.

Rules
-----
* **Specific before generic.** The table is ordered and the first rule with a
  matching word wins, so 冷笑 is read before 笑 and 怒吼 before 怒; a sneer never
  turns into a friendly smile.
* **Visible, not named.** Face and body are written as things a camera can see
  (lowered gaze, a jaw set hard), never as the emotion's name, which a video model
  cannot draw.
* **Voice-only words stay off the face.** 低声 / 沙哑 / 提高音量 describe how a line
  is said; they change the voice notes and never enter the face prompt.
* **Two face phrases at most.** Piling on expression words makes models draw none
  of them well.

The wording and values are this project's own.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Voice labels understood by the voice presets (media_compositor.EMOTION_PRESETS) and
# drama_service.dialogue_delivery_profile.
VOICE_LABELS = ("neutral", "angry", "shout", "cold", "sad", "tense", "happy", "tender")


@dataclass(frozen=True)
class EmotionRule:
    words: tuple[str, ...]
    voice: str                 # one of VOICE_LABELS
    rate: float                # speech-rate multiplier against a calm reading
    pitch: float               # pitch factor against a calm reading
    face: tuple[str, ...]      # visible facial detail, most telling first
    body: str                  # visible posture / hands
    impact: bool = False       # an outburst: the moment should land hard


# Ordered: a longer, more specific word must come before any rule whose word it contains.
RULES: tuple[EmotionRule, ...] = (
    EmotionRule(("冷笑", "嗤笑", "讥笑", "嘲笑", "嘲讽", "不屑"), "cold", 0.94, 0.97,
                ("一侧嘴角上挑而眼神发冷", "眼皮半垂斜睨"), "下巴微抬，身体后靠不动"),
    EmotionRule(("苦笑", "强颜欢笑", "惨笑"), "sad", 0.92, 0.97,
                ("嘴角勉强牵起但眉心发紧", "眼底泛红"), "肩膀垂下，手指无意识地攥着衣角"),
    EmotionRule(("狞笑", "阴笑", "奸笑"), "cold", 0.96, 0.95,
                ("咧开的嘴角配着眯起的眼", "眼神阴鸷"), "身体前倾逼近，手指慢慢收拢"),
    EmotionRule(("怒吼", "咆哮", "嘶吼", "暴怒", "爆发"), "shout", 1.14, 1.08,
                ("牙关咬紧、颈侧青筋鼓起", "眼睛瞪圆布满血丝"), "双拳攥紧、上身猛然前冲", impact=True),
    EmotionRule(("委屈", "憋屈", "受委屈"), "sad", 0.88, 0.97,
                ("下唇微颤、眼眶迅速泛红", "眼里蓄着泪没掉下来"), "双臂抱在胸前，肩膀轻轻发抖"),
    EmotionRule(("绝望", "崩溃", "心如死灰", "万念俱灰"), "sad", 0.86, 0.94,
                ("眼神失焦发空", "嘴唇发白微张"), "身体往下塌，双手捂住脸或无力垂落", impact=True),
    EmotionRule(("哽咽", "抽泣", "啜泣", "泣不成声"), "sad", 0.85, 0.96,
                ("鼻翼翕动、眼泪顺着脸颊滑下", "嘴唇抿紧又松开"), "肩膀一抽一抽，抬手用手背去擦眼泪"),
    EmotionRule(("慌张", "惊慌", "慌乱", "惊恐", "恐惧", "害怕"), "tense", 1.12, 1.05,
                ("瞳孔放大、眼睛睁圆", "脸色发白"), "手不知往哪放，身体本能地往后缩", impact=True),
    EmotionRule(("震惊", "错愕", "愣住", "难以置信"), "tense", 0.96, 1.03,
                ("眼睛猛地睁大、嘴唇微张", "呼吸一窒"), "动作停在半空，整个人僵住"),
    EmotionRule(("警惕", "戒备", "防备", "试探"), "tense", 0.97, 1.0,
                ("眉头微压、目光来回打量", "下颌收紧"), "重心后移半步，手停在身侧随时能动"),
    EmotionRule(("愤怒", "生气", "恼怒", "气愤", "怒"), "angry", 1.08, 1.04,
                ("眉头拧紧、鼻翼张开", "眼神直逼对方"), "下颌绷紧，手指攥紧或指向对方"),
    EmotionRule(("压抑", "隐忍", "克制", "强忍"), "cold", 0.93, 0.97,
                ("嘴唇抿成一线", "眼神垂下又抬起"), "肩背绷住不动，指节攥得发白"),
    EmotionRule(("冷漠", "冷淡", "漠然", "冷峻", "冷酷"), "cold", 0.94, 0.96,
                ("面无表情、眼神平直不躲闪", "嘴角平直"), "站姿笔直纹丝不动，不做多余动作"),
    EmotionRule(("得意", "嚣张", "傲慢", "轻蔑"), "cold", 1.0, 1.0,
                ("下巴抬高、眼尾带着笑意", "嘴角压不住地上扬"), "双手背在身后或抱臂，重心悠闲地靠在一侧"),
    EmotionRule(("心虚", "愧疚", "内疚", "躲闪"), "sad", 0.95, 0.98,
                ("视线躲开不敢对视", "嘴唇抿了又抿"), "手指搓着衣角，身体侧开半步"),
    EmotionRule(("释然", "如释重负", "松了口气"), "tender", 0.95, 0.99,
                ("眉头舒展、长长呼出一口气", "嘴角慢慢放松"), "肩膀落下来，整个人松弛"),
    EmotionRule(("温柔", "深情", "宠溺", "柔声"), "tender", 0.93, 0.98,
                ("目光柔和地停在对方脸上", "嘴角带着很浅的笑"), "身体微微前倾靠近，动作放轻放慢"),
    EmotionRule(("狂喜", "欣喜若狂", "大笑"), "happy", 1.08, 1.05,
                ("笑到眼睛眯起、露出牙齿", "脸颊泛红"), "身体前仰后合，手拍着桌面或膝盖", impact=True),
    EmotionRule(("开心", "欣喜", "喜悦", "高兴", "微笑", "笑"), "happy", 1.03, 1.02,
                ("眼角弯起、嘴角上扬", "眼睛发亮"), "动作轻快，肩膀放松"),
    EmotionRule(("焦急", "着急", "急切", "紧张", "焦虑"), "tense", 1.08, 1.02,
                ("眉头紧锁、嘴唇抿紧", "目光四处搜寻"), "来回踱步或手指反复敲击"),
    EmotionRule(("悲伤", "难过", "伤心", "哭"), "sad", 0.9, 0.97,
                ("眼眶泛红含着泪", "嘴角向下压"), "低头，手垂在身侧或捂住心口"),
    EmotionRule(("平静", "冷静", "淡然", "镇定"), "neutral", 1.0, 1.0,
                ("神情平稳、目光沉静",), "动作从容不急"),
)

# How a line is said, not what the face does: these change only the voice notes.
VOICE_ONLY: tuple[tuple[str, str], ...] = (
    ("低声", "压低音量"),
    ("小声", "压低音量"),
    ("耳语", "气声耳语"),
    ("沙哑", "嗓音沙哑"),
    ("嘶哑", "嗓音嘶哑"),
    ("提高音量", "提高音量"),
    ("大声", "提高音量"),
    ("一字一顿", "一字一顿、字字落重音"),
    ("拖长音", "尾音拖长"),
)

MAX_FACE_PHRASES = 2


@dataclass(frozen=True)
class EmotionReading:
    """What a piece of text says about the emotion of a moment."""

    matched: str = ""                          # the word that decided it ("" when nothing matched)
    voice: str = "neutral"
    rate: float = 1.0
    pitch: float = 1.0
    face: tuple[str, ...] = ()
    body: str = ""
    impact: bool = False
    voice_notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def visible(self) -> str:
        """The face and body, ready for a picture prompt; empty when nothing matched."""
        parts = [*self.face[:MAX_FACE_PHRASES], self.body]
        return "，".join(part for part in parts if part)


def _strip_voice_only(text: str) -> tuple[str, tuple[str, ...]]:
    notes: list[str] = []
    for word, note in VOICE_ONLY:
        if word in text:
            text = text.replace(word, " ")
            if note not in notes:
                notes.append(note)
    return text, tuple(notes)


def read_emotion(*texts: str | None) -> EmotionReading:
    """Read the emotion of a moment from its notes, line and description, in that order of authority.

    Each text is read on its own and the first that names an emotion decides, so an
    explicit delivery note beats a guess from the description. Voice-only words are
    collected from all of them and never decide the face.
    """
    voice_notes: list[str] = []
    cleaned: list[str] = []
    for raw in texts:
        text, notes = _strip_voice_only(str(raw or ""))
        cleaned.append(text)
        voice_notes.extend(note for note in notes if note not in voice_notes)
    for text in cleaned:
        for rule in RULES:
            word = next((candidate for candidate in rule.words if candidate in text), "")
            if word:
                return EmotionReading(
                    matched=word, voice=rule.voice, rate=rule.rate, pitch=rule.pitch,
                    face=rule.face[:MAX_FACE_PHRASES], body=rule.body, impact=rule.impact,
                    voice_notes=tuple(voice_notes),
                )
    return EmotionReading(voice_notes=tuple(voice_notes))


def check_order() -> list[str]:
    """Rules whose word is shadowed by an earlier, shorter word that it contains (should be empty)."""
    problems: list[str] = []
    seen: list[tuple[int, str]] = []
    for index, rule in enumerate(RULES):
        for word in rule.words:
            for earlier_index, earlier in seen:
                if earlier != word and earlier in word and earlier_index < index:
                    problems.append(f"「{word}」排在「{earlier}」之后，会被它抢先命中")
        seen.extend((index, word) for word in rule.words)
    return problems


__all__ = ["EmotionReading", "EmotionRule", "MAX_FACE_PHRASES", "RULES", "VOICE_LABELS", "VOICE_ONLY", "check_order", "read_emotion"]
