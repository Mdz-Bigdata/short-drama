# -*- coding: utf-8 -*-
"""Style packs: the look a whole production is locked to, as data.

A production commits to one look and every prompt restates it verbatim — that is the
only thing that keeps a series from drifting between clips. A pack holds what the look
is made of:

- the **style lock**: sentences copied into every prompt and never rewritten;
- a **tone layer** formula that changes per segment (genre overlay, tension, ending beat,
  aspect, time of day) so the lock does not make everything feel the same;
- a **camera kit** (body, lens, stock, grain) with purpose-keyed alternates;
- **palette rules**: through-colours with HEX values and the tonal knobs;
- **positive boosters** for the medium (de-AI wording for live action, line and shading
  words for animation), **negatives** in tiers, and **anti-leak** guards for references
  drawn in a different medium (a colour card, a design sheet, a storyboard, a white model);
- **sound defaults** and the sentence an extension must repeat.

The packs are the project's own writing. The two engine documents they follow are
described in ``docs/style-packs/RESEARCH.md``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Medium = Literal["live_action", "anime_2d", "anime_3d", "mixed"]
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


class CameraKit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(max_length=120)
    lens: str = Field(max_length=120)
    stock: str = Field("", max_length=120)
    grain: str = Field("", max_length=60)
    # purpose → the alternate rig a shot may swap to (action, emotion, tension, chase…)
    alternates: dict[str, str] = Field(default_factory=dict)
    per_shot_swap_allowed: bool = False


class PaletteColour(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=40)
    hex: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    # The object the colour is bound to. "阴影" or "氛围" is not an object: a colour that
    # is not tied to something visible drifts.
    bound_to: str = Field("", max_length=80)


class PaletteRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    through_colours: list[PaletteColour] = Field(default_factory=list, max_length=6)
    card_size: int = Field(13, ge=3, le=24)
    carried: int = Field(7, ge=0, le=24)
    knobs: dict[str, str] = Field(default_factory=dict)  # contrast / temperature / saturation / vignette …
    mask_dark_hex: str = Field("#1A1610", pattern=r"^#[0-9A-Fa-f]{6}$")
    mask_light_hex: str = Field("#E8E8DC", pattern=r"^#[0-9A-Fa-f]{6}$")


class SoundDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bgm_policy: Literal["none", "white_noise", "single_instrument"] = "none"
    ambience_allowed: bool = True
    signature_sfx: list[str] = Field(default_factory=list, max_length=20)
    closing_sentence: str = Field(
        "仅生成动作音效、对白音效与环境音效；不要BGM；无字幕；无水印。", max_length=200,
    )


class StylePack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9_]{3,40}$")
    name: str = Field(max_length=60)
    medium: Medium
    summary: str = Field(max_length=300)
    lock: list[str] = Field(min_length=1, max_length=20)
    tone_slots: list[str] = Field(default_factory=list, max_length=8)
    tone_default: str = Field("", max_length=300)
    camera: CameraKit
    palette: PaletteRules = Field(default_factory=PaletteRules)
    positives: list[str] = Field(default_factory=list, max_length=30)
    negatives: list[str] = Field(default_factory=list, max_length=40)
    situational_negatives: dict[str, list[str]] = Field(default_factory=dict)
    anti_leak: list[str] = Field(default_factory=list, max_length=12)
    extension_restatement: str = Field(max_length=300)
    sound: SoundDefaults = Field(default_factory=SoundDefaults)
    # What the Ark request's ``style_caption`` field carries for this look.
    style_caption: str = Field(max_length=600)
    # Words that name this pack in a free-text style setting.
    aliases: list[str] = Field(default_factory=list, max_length=30)

    @property
    def lock_text(self) -> str:
        return "[STYLE LOCK]\n" + "\n".join(f"+ {line}" if index else line for index, line in enumerate(self.lock))


# ---------------------------------------------------------------------------------------------
# The packs

_LIVE_ACTION_NEGATIVES = [
    "NOT 3D rendered", "NOT CGI", "NOT video game graphics", "NOT plastic look", "NOT wax figure skin",
    "NOT cartoon", "NOT anime", "NOT illustration", "NOT 强磨皮美颜", "无字幕", "无水印",
]
_LIVE_ACTION_POSITIVES = [
    "photorealistic live-action footage", "real physical scene captured through a camera lens",
    "film grain visible", "lens imperfection", "micro-details and surface wear",
    "natural lighting inconsistency", "dust particles in air", "motion blur on fast objects",
]
_SITUATIONAL = {
    "multi_person": ["绝对禁止面部特征互换", "绝对禁止换装", "no character face-swap", "no identity confusion"],
    "extension": ["禁止生硬切镜", "禁止物体凭空出现", "禁止人物凭空消失"],
    "audio_driven": ["no lip-sync error", "口型与台词逐字同步"],
    "green_screen": ["no glowing edge around composited characters", "背景无渐变无阴影"],
    "fight": ["NOT slow motion", "NOT speed ramping", "no frozen pose", "no foot sliding"],
    "night": ["NOT clear blue sky", "NOT even daylight"],
}

FILM_35MM = StylePack(
    id="film_35mm",
    name="35mm 胶片电影",
    medium="live_action",
    summary="35mm 胶片实拍质感：可见颗粒、实景光源、高光光晕、大气薄雾，胶片印片而非数字电影观感。",
    lock=[
        "Shot on 35mm Kodak Vision3 500T film stock + analog film grain visible",
        "practical light only + naturalistic handheld breathing",
        "painterly desaturation + photochemical film texture",
        "slight halation on highlights + organic film noise",
        "heavy atmospheric haze + tactile real-world materials",
        "film print look not digital cinema look",
        "photorealistic film still aesthetic",
        "real physical scene captured through a camera lens + not a 3D render",
    ],
    tone_slots=["动作/情绪参考片", "节奏/张力词", "结尾beat", "画幅", "光线时段"],
    tone_default="日常静默调性 + 克制张力 + 结尾释然beat + 9:16 + 自然光时段",
    camera=CameraKit(
        body="ARRI 35mm 胶片机", lens="35mm / 50mm 定焦", stock="Kodak Vision3 500T", grain="中等颗粒",
        alternates={}, per_shot_swap_allowed=False,
    ),
    palette=PaletteRules(
        through_colours=[
            PaletteColour(name="暖光", hex="#E8B06A", bound_to="室内实景灯光"),
            PaletteColour(name="青灰", hex="#5B6770", bound_to="阴面墙体与铁皮"),
        ],
        knobs={"contrast": "中低对比，暗部有细节", "temperature": "偏暖，钨丝灯平衡", "saturation": "低饱和", "vignette": "轻微暗角"},
    ),
    positives=_LIVE_ACTION_POSITIVES,
    negatives=_LIVE_ACTION_NEGATIVES,
    situational_negatives=_SITUATIONAL,
    anti_leak=[
        "色卡反偷懒铁律：色卡图仅作色值参考 + 绝对禁止白色背景 + 绝对禁止色块/色板构图 + 绝对禁止HEX文字",
        "设定图反偷懒铁律：设定图仅作造型参考 + 绝对禁止多格拼版 + 绝对禁止摄影棚白底 + 绝对禁止视图标注文字 + 角色必须处于剧情动作中",
        "故事板反偷懒铁律：故事板仅作构图机位参考 + 绝对禁止铅笔素描质感 + 绝对禁止纸张底色 + 绝对禁止手绘linework",
        "白模反偷懒铁律：白模仅作调度与机位参考 + 绝对禁止白模材质残留 + 绝对禁止轨迹线、坐标线与相机cone入画",
    ],
    extension_restatement="全片保持35mm胶片质感、胶片颗粒与色卡色彩不变。",
    sound=SoundDefaults(bgm_policy="none", ambience_allowed=True, signature_sfx=[]),
    style_caption=(
        "35mm 胶片电影实拍质感，photorealistic live-action film still, Kodak Vision3 500T grain, "
        "practical light, halation on highlights, atmospheric haze, film print look; "
        "not anime, not cartoon, not 3d render, not illustration"
    ),
    aliases=["胶片", "35mm", "film", "胶片电影", "realistic", "写实", "真人", "live action", "电影感", "cinematic"],
)

ATOM_PUNK = StylePack(
    id="atom_punk",
    name="原子朋克废土",
    medium="live_action",
    summary="1950 年代复古未来主义遇上末世废土：电子管、黄铜、铆钉钢板、锈蚀与剥落漆面，暖主光配冷轮廓光，实拍工业质感。",
    lock=[
        "1950s retro-futurism meets post-apocalyptic wasteland + cinematic industrial texture",
        "vacuum-tube dials and tube glow + brass gears + riveted steel plate + rusted metal + peeling paint",
        "rough welds beside precision gauges + worn leather + oxidised copper",
        "warm key light + cool rim light + local highlights from indicator lamps",
        "ARRI ALEXA Mini LF + Cooke S7/i 35mm f/2.8 look + Kodak Vision3 500T grain",
        "hyperrealistic live-action footage quality + real physical scene + not a 3D render",
    ],
    tone_slots=["类型片叠加", "节奏/张力词", "结尾beat", "画幅", "光线时段"],
    tone_default="废土生存调性 + 缓慢逼近的张力 + 结尾悬念beat + 9:16 + 黄昏golden hour",
    camera=CameraKit(
        body="ARRI ALEXA Mini LF", lens="Cooke S7/i 35mm f/2.8", stock="Kodak Vision3 500T", grain="中等颗粒",
        alternates={
            "action": "16mm 广角，夸张透视", "emotion": "85mm 压缩空间的情绪特写",
            "tension": "CCTV 监控视角", "chase": "GoPro 鱼眼 FPV 追逐",
        },
        per_shot_swap_allowed=True,
    ),
    palette=PaletteRules(
        through_colours=[
            PaletteColour(name="琥珀", hex="#FFBF00", bound_to="电子管与仪表灯"),
            PaletteColour(name="铜绿", hex="#4A7C59", bound_to="氧化铜管件"),
            PaletteColour(name="深金属灰", hex="#2C3539", bound_to="铆钉钢板"),
        ],
        knobs={
            "contrast": "中高对比，暗部深但有细节", "temperature": "偏暖，钨丝灯平衡",
            "saturation": "中高饱和但不过饱和", "vignette": "轻微暗角 + 边缘色散",
        },
    ),
    positives=[
        *_LIVE_ACTION_POSITIVES, "rust oxidation layers", "oil stains", "paint scratches",
        "breathing micro-movement", "anamorphic flare from warning lights",
    ],
    negatives=[
        *_LIVE_ACTION_NEGATIVES, "NOT Unreal look", "NOT doll skin", "NOT over-smooth surfaces",
        "NOT clean pristine environment", "NOT stiff mannequin posture", "NOT flat lighting",
    ],
    situational_negatives={
        **_SITUATIONAL,
        "led_face_panel": ["no realistic human face on this character", "像素质感仅限面板，画面整体不得变成游戏或动画观感"],
    },
    anti_leak=[
        "色卡反偷懒铁律：色卡图仅作色值参考 + 绝对禁止白色背景 + 绝对禁止色块/色板构图 + 绝对禁止HEX文字",
        "设定图反偷懒铁律：设定图仅作造型参考 + 绝对禁止多格拼版 + 绝对禁止摄影棚白底 + 绝对禁止视图标注文字",
        "白模反偷懒铁律：白模仅作调度与机位参考 + 绝对禁止白模材质残留 + 绝对禁止轨迹线、坐标线与相机cone入画",
        "像素面板铁律：像素观感只出现在面板上，身体、服装与世界保持实拍质感",
    ],
    extension_restatement="全片保持原子朋克实拍工业质感、Vision3 500T 颗粒与色卡色彩不变；磨损与油污延续并可累积。",
    sound=SoundDefaults(
        bgm_policy="none", ambience_allowed=True,
        signature_sfx=["金属碰撞 metal clank", "液压嘶声 hydraulic hiss", "盖革计数器滴答 Geiger ticks", "电子管嗡鸣 tube hum", "面板提示音 panel beep"],
    ),
    style_caption=(
        "原子朋克废土实拍质感，1950s retro-futurism, hyperrealistic live-action footage, "
        "vacuum tubes, brass, riveted steel, rust and peeling paint, warm key with cool rim light, "
        "Vision3 500T grain; not anime, not cartoon, not 3d render, not video game graphics"
    ),
    aliases=["原子朋克", "atom punk", "atompunk", "atom_punk", "废土", "复古未来", "retro-futur"],
)

ANIME_2D_CEL = StylePack(
    id="anime_2d_cel",
    name="2D 赛璐珞漫剧",
    medium="anime_2d",
    summary="平涂赛璐珞动画：干净线稿、二阶色块阴影、明快低饱和色彩、柔光正面照明。",
    lock=[
        "2D cel-shaded anime illustration + clean consistent line art + flat colour fills with two-step shadows",
        "consistent character proportions and face model across every shot",
        "soft frontal diffuse lighting + macaron pastel palette",
        "hand-drawn animation look + no photographic texture + no 3D render",
    ],
    tone_slots=["情绪调性", "节奏词", "结尾beat", "画幅", "光线时段"],
    tone_default="甜宠治愈调性 + 轻快节奏 + 结尾会心一笑beat + 9:16 + 午后柔光",
    camera=CameraKit(body="动画摄影台", lens="标准 50mm 等效构图", stock="", grain="无颗粒", per_shot_swap_allowed=False),
    palette=PaletteRules(
        through_colours=[
            PaletteColour(name="樱粉", hex="#F5B7C6", bound_to="女主发饰与腮红"),
            PaletteColour(name="天蓝", hex="#8EC5E8", bound_to="校服与天空"),
        ],
        knobs={"contrast": "低对比", "temperature": "中性偏暖", "saturation": "中高饱和", "vignette": "无"},
        mask_dark_hex="#2B2B3A", mask_light_hex="#FFFFFF",
    ),
    positives=["crisp line art", "flat cel shading", "clean two-tone shadows", "vivid but soft colours", "expressive anime eyes"],
    negatives=[
        "NOT photorealistic", "NOT live action", "NOT 3D render", "NOT film grain", "NOT lens flare",
        "NOT realistic skin pores", "no sketch lines left unfinished", "无字幕", "无水印", "no speech bubbles", "no halftone dots",
    ],
    situational_negatives={
        "multi_person": ["绝对禁止角色脸型与发型互换", "no identity confusion"],
        "extension": ["禁止生硬切镜", "禁止角色凭空出现或消失"],
        "fight": ["no motion smear blobs", "no extra limbs"],
    },
    anti_leak=[
        "设定图反偷懒铁律：设定图仅作造型参考 + 绝对禁止三视图拼版入画 + 绝对禁止白底设定板构图 + 绝对禁止视图标注文字",
        "实拍参考反偷懒铁律：实拍参考图仅作构图与光位参考 + 绝对禁止照片质感、皮肤毛孔与镜头颗粒进入画面",
    ],
    extension_restatement="全片保持同一套线稿粗细、赛璐珞二阶阴影与色卡色彩不变，角色比例与脸型不变。",
    sound=SoundDefaults(bgm_policy="none", ambience_allowed=True, signature_sfx=[]),
    style_caption=(
        "2D 赛璐珞动画漫剧，cel-shaded anime illustration, clean line art, flat colours with two-step shadows, "
        "consistent character model; not photorealistic, not live action, not 3d render, no film grain"
    ),
    aliases=["2d", "二维", "赛璐珞", "cel", "日漫", "动画", "anime", "漫剧", "2D漫剧", "国漫2d"],
)

ANIME_3D_CG = StylePack(
    id="anime_3d_cg",
    name="3D 国漫 CG",
    medium="anime_3d",
    summary="UE5 / C4D 级别的 3D 国漫渲染：PBR 材质、体积光与丁达尔光束、电影景深，角色为风格化写实建模而非真人。",
    lock=[
        "3D stylised CG animation rendered in a UE5-class engine + PBR materials + ray-traced lighting",
        "stylised realistic character models with consistent face rigs + flowing hair and cloth simulation",
        "volumetric light shafts + cinematic depth of field",
        "not live-action footage + not 2D flat illustration",
    ],
    tone_slots=["类型调性", "节奏词", "结尾beat", "画幅", "光线时段"],
    tone_default="仙侠史诗调性 + 蓄力后爆发的节奏 + 结尾悬念beat + 9:16 + 逆光时段",
    camera=CameraKit(body="虚拟摄影机", lens="35mm / 85mm 等效", stock="", grain="无颗粒", per_shot_swap_allowed=True),
    palette=PaletteRules(
        through_colours=[
            PaletteColour(name="鎏金", hex="#D4AF37", bound_to="法宝与纹饰"),
            PaletteColour(name="石青", hex="#2E5C8A", bound_to="道袍与远山"),
            PaletteColour(name="朱砂", hex="#B0312A", bound_to="符箓与殿柱"),
        ],
        knobs={"contrast": "中高对比", "temperature": "冷暖对撞", "saturation": "中高饱和", "vignette": "轻微"},
    ),
    positives=["高精度 3D 建模", "PBR 材质细节", "volumetric lighting", "subsurface scattering skin", "cloth and hair simulation"],
    negatives=[
        "NOT live-action photo", "NOT real human actor", "NOT 2D flat illustration", "NOT low-poly game asset",
        "NOT plastic doll look", "no uncanny valley face", "无字幕", "无水印",
    ],
    situational_negatives={
        "multi_person": ["绝对禁止角色模型互换", "no identity confusion"],
        "extension": ["禁止生硬切镜", "禁止角色凭空出现或消失"],
        "fight": ["no limb clipping", "no extra limbs", "no VFX hiding the contact point"],
    },
    anti_leak=[
        "设定图反偷懒铁律：三视图仅作建模参考 + 绝对禁止拼版与白底设定板构图 + 绝对禁止视图标注文字",
        "白模反偷懒铁律：白模仅作调度与机位参考 + 绝对禁止白模材质残留 + 绝对禁止轨迹线、坐标线与相机cone入画",
    ],
    extension_restatement="全片保持同一套 3D 材质、光照方案与色卡色彩不变，角色模型与脸部绑定不变。",
    sound=SoundDefaults(bgm_policy="none", ambience_allowed=True, signature_sfx=[]),
    style_caption=(
        "3D 国漫 CG 动画，stylised 3D CG animation, UE5-class PBR rendering, volumetric light, "
        "consistent character models; not live action, not real human, not 2d flat illustration"
    ),
    aliases=["3d", "三维", "国漫", "cg", "ue5", "c4d", "3D国漫", "3d动画", "仙侠3d"],
)

CINEMATIC_REALISM = StylePack(
    id="cinematic_realism",
    name="真人电影写实",
    medium="live_action",
    summary="通用真人实拍电影质感（项目默认）：真实皮肤纹理、自然光、浅景深、轻微 35mm 颗粒。",
    lock=[
        "photorealistic live-action cinematic film still + real human skin texture",
        "natural lighting + shallow depth of field + subtle 35mm film grain",
        "real physical scene captured through a camera lens + not a 3D render",
    ],
    tone_slots=["类型调性", "节奏词", "结尾beat", "画幅", "光线时段"],
    tone_default="都市剧情调性 + 稳健节奏 + 结尾钩子beat + 9:16 + 自然光时段",
    camera=CameraKit(body="数字电影机", lens="35mm / 50mm / 85mm", stock="", grain="轻微 35mm 颗粒", per_shot_swap_allowed=True),
    palette=PaletteRules(through_colours=[], knobs={"contrast": "中等", "temperature": "按场景", "saturation": "中等", "vignette": "轻微"}),
    positives=_LIVE_ACTION_POSITIVES,
    negatives=_LIVE_ACTION_NEGATIVES,
    situational_negatives=_SITUATIONAL,
    anti_leak=[
        "设定图反偷懒铁律：五视图仅作造型参考 + 绝对禁止多格拼版 + 绝对禁止摄影棚白底 + 绝对禁止视图标注文字",
        "故事板反偷懒铁律：分镜图仅作构图机位参考 + 绝对禁止九宫格拼版、线稿质感与文字标注进入画面",
    ],
    extension_restatement="全片保持真人实拍电影质感与色彩基调不变。",
    sound=SoundDefaults(bgm_policy="none", ambience_allowed=True, signature_sfx=[]),
    style_caption=(
        "真实电影质感，实拍写真，photorealistic live-action cinematic film still, "
        "real human skin texture, natural lighting, 35mm film grain, shallow depth of field; "
        "绝非动画、绝非卡通、绝非3D渲染、绝非插画、绝非草图 (not anime, not cartoon, not 3d render, "
        "not illustration, not sketch, not concept art)"
    ),
    aliases=["default", "默认", "写实电影", "真人电影写实", "cyberpunk", "retro", "noir", "photoreal"],
)

_PACKS: tuple[StylePack, ...] = (CINEMATIC_REALISM, FILM_35MM, ATOM_PUNK, ANIME_2D_CEL, ANIME_3D_CG)
DEFAULT_PACK_ID = CINEMATIC_REALISM.id


def list_packs() -> list[StylePack]:
    return list(_PACKS)


def get_pack(pack_id: str) -> StylePack | None:
    key = str(pack_id or "").strip().lower().replace("-", "_")
    return next((pack for pack in _PACKS if pack.id == key), None)


def resolve_pack(config: Mapping[str, Any] | None) -> StylePack:
    """The pack a task is locked to: an explicit ``style_pack``, else the one its style words name.

    An unknown or empty setting is the project default, which reproduces the look every
    production had before packs existed.
    """
    config = config or {}
    explicit = get_pack(str(config.get("style_pack") or ""))
    if explicit is not None:
        return explicit
    text = " ".join(str(config.get(key) or "") for key in ("style_pack", "visual_style", "director_style")).lower()
    if text.strip():
        # Longest alias wins so 「3D国漫」 is not claimed by 「国漫」 of another pack.
        ranked = sorted(((alias, pack) for pack in _PACKS for alias in pack.aliases), key=lambda item: -len(item[0]))
        for alias, pack in ranked:
            if alias.lower() in text:
                return pack
    return CINEMATIC_REALISM


# ---------------------------------------------------------------------------------------------
# Tone layer, palette card, negatives, rules


def tone_line(pack: StylePack, values: Mapping[str, str] | None = None) -> str:
    """The per-segment tone line: the pack's slots filled from ``values``, defaults elsewhere."""
    values = values or {}
    filled = [str(values.get(slot) or "").strip() for slot in pack.tone_slots]
    if not any(filled):
        return pack.tone_default
    defaults = [part.strip() for part in pack.tone_default.split("+")]
    parts = [filled[index] or (defaults[index] if index < len(defaults) else "") for index in range(len(pack.tone_slots))]
    return " + ".join(part for part in parts if part)


def style_lock_block(pack: StylePack, tone: Mapping[str, str] | str | None = None) -> str:
    """The first layer of every prompt: the lock verbatim, then this segment's tone line."""
    line = tone if isinstance(tone, str) and tone.strip() else tone_line(pack, tone if isinstance(tone, Mapping) else None)
    return f"{pack.lock_text}\n{line}。"


class PaletteCard(BaseModel):
    """One scene group's colour card: N colours, each bound to a visible object."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(max_length=120)
    colours: list[PaletteColour] = Field(min_length=3, max_length=24)
    carried: int = Field(0, ge=0)

    @property
    def top(self) -> list[PaletteColour]:
        return self.colours[:5]


def build_palette_card(
    pack: StylePack, *, project: str, episode: int, segment: int, subject: str,
    new_colours: Sequence[PaletteColour], carried: Sequence[PaletteColour] = (),
) -> PaletteCard:
    """Carry the through-colours (and whatever the previous card carried), then add the new ones.

    Every colour must be bound to a visible object; a colour bound to nothing, or to an
    abstraction such as 阴影 / 氛围, is refused.
    """
    colours: list[PaletteColour] = []
    seen: set[str] = set()
    for colour in (*pack.palette.through_colours, *carried, *new_colours):
        if not colour.bound_to.strip() or colour.bound_to.strip() in _ABSTRACT_BINDINGS:
            raise ValueError(f"色卡「{colour.name}」必须绑定具体物件，「{colour.bound_to or '空'}」不是物件")
        if colour.hex.upper() in seen:
            continue
        seen.add(colour.hex.upper())
        colours.append(colour)
    if len(colours) > pack.palette.card_size:
        raise ValueError(f"色卡最多 {pack.palette.card_size} 色，现有 {len(colours)} 色")
    carried_count = len({c.hex.upper() for c in (*pack.palette.through_colours, *carried)})
    return PaletteCard(title=f"{project} EP{episode} SEG{segment} - {subject} COLOR REFERENCE", colours=colours, carried=carried_count)


_ABSTRACT_BINDINGS = frozenset({"阴影", "氛围", "情绪", "高光", "暗部", "背景", "整体", "shadow", "mood", "ambience", "background"})


def palette_lines(card: PaletteCard, card_ref: str = "") -> list[str]:
    """The three-part palette instruction: card anchor, the strict-N sentence, top HEX inline."""
    strict = f"所有色彩严格按色卡{len(card.colours)}色执行 + 不可偏离色板"
    inline = "；".join(f"{c.bound_to}{c.name}{c.hex}" for c in card.top)
    lines = [f"{card_ref}作为整段色卡锚定 + {strict}。" if card_ref else strict + "。"]
    if inline:
        lines.append(f"主要色值：{inline}。")
    return lines


def negatives_for(pack: StylePack, situations: Iterable[str] = (), extra: Iterable[str] = ()) -> list[str]:
    """Base negatives, then the situational add-ons that apply, then per-film custom items; no duplicates."""
    terms: list[str] = list(pack.negatives)
    for situation in situations:
        terms.extend(pack.situational_negatives.get(situation, []))
    terms.extend(str(item).strip() for item in extra if str(item).strip())
    return list(dict.fromkeys(terms))


# Reference kinds whose medium is not the finished frame: each needs its anti-leak guard.
_LEAK_KINDS: dict[str, str] = {
    "palette_card": "色卡", "design_sheet": "设定图", "five_view": "设定图", "storyboard": "故事板", "blockout": "白模",
    "live_photo": "实拍参考",
}

IRON_RULES: dict[str, tuple[str, str]] = {
    "identity": ("主体身份铁律", "{subjects}严格按各自参考图渲染 + 不可改造 + 禁止互串。"),
    "parts": ("造型部件铁律", "部件清单全部可见 + 禁止增减配件 + 禁止左右换位。"),
    "camera": ("机位铁律", "景别与运镜只用本镜声明的方式 + 无变焦 + 无环绕 + 仅 handheld 微抖。"),
    "palette": ("色卡锚定铁律", "所有色彩严格按色卡执行 + 不可偏离色板。"),
    "physics": ("物理铁律", "道具不凭空消失、受力合理、动作因果清楚。"),
    "mask": ("遮罩铁律", "遮罩必须接近全黑或全白（near total）+ 禁止半灰 + 遮罩之后禁止再出现可见元素。"),
    "extension": ("延长重申铁律", "{restatement}"),
    "reference_cap": ("参考图限量铁律", "单次投喂核心锚定不超过 9 个，超限按场景组分批。"),
    "lip_sync": ("口型同步铁律", "嘴部动作与台词逐字同步；无台词时闭口聆听。"),
    "multi_person": ("多人身份铁律", "多人同框时各按各自设定图渲染 + 绝对禁止面部特征互换 + 绝对禁止换装。"),
}


def iron_rules(
    pack: StylePack, *, subjects: Sequence[str] = (), reference_kinds: Iterable[str] = (), rule_ids: Iterable[str] = (),
) -> list[str]:
    """Named rules for one prompt: the requested ones, the multi-person rule when two or more subjects
    are named, the pack's style rule, and an anti-leak rule for every non-final-medium reference kind."""
    wanted = list(dict.fromkeys(rule_ids))
    if len(subjects) >= 2 and "multi_person" not in wanted:
        wanted.append("multi_person")
    lines: list[str] = []
    for rule_id in wanted:
        if rule_id not in IRON_RULES:
            raise KeyError(f"unknown iron rule: {rule_id}")
        name, template = IRON_RULES[rule_id]
        body = template.format(subjects="、".join(subjects) or "主体", restatement=pack.extension_restatement)
        lines.append(f"{name}：{body}")
    lines.append(f"风格铁律：{' + '.join(pack.negatives[:5])}。")
    kinds = {_LEAK_KINDS[kind] for kind in reference_kinds if kind in _LEAK_KINDS}
    for guard in pack.anti_leak:
        if guard.split("反偷懒铁律")[0] in kinds:
            lines.append(guard)
    return lines


def caption_for(pack: StylePack) -> str:
    return pack.style_caption


def image_style_line(pack: StylePack, *, lighting: str = "", aspect_ratio: str = "9:16") -> str:
    """The style sentence a still prompt carries: the pack's own anchor, never a fixed photoreal one."""
    lighting_part = f"；{lighting.strip()} lighting style" if lighting.strip() else ""
    return f"{pack.style_caption}{lighting_part}；画幅 {aspect_ratio}"


_NON_REALISTIC_CLAUSE = "并严禁任何非写实风格"


def identity_negative(pack: StylePack, base: str) -> str:
    """The de-identification negatives, minus the anti-animation clause when the pack is animated.

    The clause bans anime, cartoon and 3D renders outright, which is right for live action and
    exactly wrong for a 2D or 3D drama: it would fight the pack's own look.
    """
    if pack.medium == "live_action" or _NON_REALISTIC_CLAUSE not in base:
        return base
    head = base.split(_NON_REALISTIC_CLAUSE)[0].rstrip("；;， ")
    return head + ")" if base.startswith("(") and not head.endswith(")") else head


def describe(pack: StylePack) -> dict[str, Any]:
    """What the API and the settings UI show for a pack."""
    return {
        "id": pack.id, "name": pack.name, "medium": pack.medium, "summary": pack.summary,
        "lock": list(pack.lock), "tone_slots": list(pack.tone_slots), "tone_default": pack.tone_default,
        "camera": pack.camera.model_dump(), "through_colours": [c.model_dump() for c in pack.palette.through_colours],
        "negatives": list(pack.negatives), "sound": pack.sound.model_dump(),
    }


__all__ = [
    "ANIME_2D_CEL", "ANIME_3D_CG", "ATOM_PUNK", "CINEMATIC_REALISM", "DEFAULT_PACK_ID", "FILM_35MM", "IRON_RULES",
    "CameraKit", "PaletteCard", "PaletteColour", "PaletteRules", "SoundDefaults", "StylePack",
    "build_palette_card", "caption_for", "describe", "get_pack", "identity_negative", "image_style_line",
    "iron_rules", "list_packs", "negatives_for",
    "palette_lines", "resolve_pack", "style_lock_block", "tone_line",
]
