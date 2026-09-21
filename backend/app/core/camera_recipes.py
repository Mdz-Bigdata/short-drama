"""Camera-move recipes: narrative category + intensity → one composed move.

A recipe is assembled from six slots — camera move, camera angle, subject
action, environment change, light mood, image texture — plus a negative line,
so a shot's move is written the way video models read it instead of as a bare
verb. Moves come from the provider vocabulary in ``camera_motion`` so the
contract stays executable; the phrasing here is the project's own.

The anti-repeat rule: lock style and texture, rotate exactly one of move,
angle, rhythm or environment between adjacent shots.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.camera_motion import CAMERA_MOTION_LABELS, normalize_camera_motion, render_camera_motion

Intensity = str  # "strong" | "medium" | "soft"

ANGLES: tuple[tuple[str, str, str], ...] = (
    ("eye_level", "平视", "eye-level"),
    ("low_angle", "仰拍", "low angle"),
    ("high_angle", "俯拍", "high angle"),
    ("dutch_angle", "荷兰角", "dutch angle"),
    ("over_shoulder", "过肩", "over-the-shoulder"),
    ("pov", "主观", "first person POV"),
    ("low_ground", "低位贴地", "low ground-hugging"),
)
RHYTHMS: tuple[tuple[str, str, str], ...] = (
    ("slow", "慢节奏", "slow"),
    ("steady", "稳定匀速", "smooth steady"),
    ("fast", "快节奏", "fast"),
    ("slow_motion", "慢动作升格", "slow motion, high frame rate"),
    ("shaky", "轻微手持", "subtle handheld"),
    ("burst", "蓄力后短促爆发", "long hold then a short burst"),
)
_ANGLE_ZH = {key: zh for key, zh, _ in ANGLES}
_ANGLE_EN = {key: en for key, _, en in ANGLES}
_RHYTHM_ZH = {key: zh for key, zh, _ in RHYTHMS}
_RHYTHM_EN = {key: en for key, _, en in RHYTHMS}

# category -> (label, purpose, {intensity: (move, angle, rhythm, zh_action_hint, en_action_hint)})
RECIPE_CATEGORIES: dict[str, dict[str, Any]] = {
    "entrance": {
        "label": "人物出场",
        "purpose": "交代人物气场与情绪起点",
        "levels": {
            "strong": ("Push In", "low_angle", "fast", "快速推向面部，眼神锐利", "rapid push-in to the face, sharp eyes"),
            "medium": ("Push In", "eye_level", "slow", "缓慢靠近人物，表情逐渐清晰", "slow push-in, expression comes into focus"),
            "soft": ("Orbit", "eye_level", "slow", "缓慢环绕，衣摆与发丝随风", "slow orbit, cloth and hair moving in the wind"),
        },
    },
    "tracking": {
        "label": "移动跟拍",
        "purpose": "人物在空间中移动，环境持续变化",
        "levels": {
            "strong": ("Tracking Shot", "low_ground", "fast", "贴地紧跟冲刺，地面速度感明显", "ground-hugging follow of a sprint"),
            "medium": ("Truck Right", "eye_level", "steady", "侧面平行跟拍行走，环境掠过", "side tracking of the walk, environment sliding by"),
            "soft": ("Tracking Shot", "eye_level", "slow", "从背后缓缓跟随，空间渐渐展开", "gentle follow from behind, space opening up"),
        },
    },
    "dialogue": {
        "label": "对话视角",
        "purpose": "把观众放进对话的一方",
        "levels": {
            "strong": ("Push In", "over_shoulder", "slow", "越过前景肩膀缓推，视线落在对方脸上", "over-the-shoulder slow push onto the listener's face"),
            "medium": ("Static", "over_shoulder", "steady", "过肩固定，前景肩膀轻微虚化", "locked over-the-shoulder, foreground shoulder softly blurred"),
            "soft": ("Static", "eye_level", "steady", "平视双人固定，两人视线在中心相交", "eye-level two-shot, eyelines meeting at centre"),
        },
    },
    "opening": {
        "label": "大片开场",
        "purpose": "空间一次展开，建立世界观",
        "levels": {
            "strong": ("Pedestal Down", "high_angle", "fast", "高空俯冲到人物身边，空间瞬间展开", "aerial dive down to the character, space unfolds at once"),
            "medium": ("Pedestal Up", "eye_level", "slow", "由低到高抬升，完整交代人物与环境", "crane up revealing character and environment"),
            "soft": ("Pull Out", "eye_level", "slow", "从近景缓缓拉远，人物在空间中变小", "slow dolly out from close-up to wide"),
        },
    },
    "transition": {
        "label": "转场慢镜",
        "purpose": "以运镜完成时空切换或情绪定格",
        "levels": {
            "strong": ("Pan Right", "eye_level", "fast", "快速甩动带出方向性模糊接下一场", "whip pan with directional blur into the next scene"),
            "medium": ("Truck Right", "eye_level", "fast", "快速横移带动动态模糊切换空间", "fast lateral move with motion blur switching space"),
            "soft": ("Orbit", "eye_level", "slow_motion", "时间放慢，镜头环绕定格瞬间", "slowed time, camera orbiting the frozen instant"),
        },
    },
    "fight_rhythm": {
        "label": "打斗节奏",
        "purpose": "出招与反馈的节拍",
        "levels": {
            "strong": ("Tracking Shot", "eye_level", "burst", "镜头跟剑锋走，出手瞬间短促急推后骤停", "camera rides the blade, a short burst on the strike then a hard stop"),
            "medium": ("Orbit", "eye_level", "fast", "人物侧身闪避，镜头同步环绕", "character dodges, camera orbits in sync"),
            "soft": ("Zoom In", "eye_level", "slow", "聚焦手与剑柄，剑刃缓缓出鞘", "close on hand and hilt, blade slowly unsheathed"),
        },
    },
    "fight_climax": {
        "label": "打斗高潮",
        "purpose": "终局对决与冲击反馈",
        "levels": {
            "strong": ("Orbit", "low_ground", "burst", "360 度环绕双方，爆发瞬间镜头震动、碎屑飞散", "360 orbit around both fighters, camera shake and debris on impact"),
            "medium": ("Shake", "eye_level", "fast", "冲击瞬间轻微震动，力量感直接", "slight shake on impact, direct sense of force"),
            "soft": ("Orbit", "eye_level", "slow_motion", "动作定格在高速瞬间，镜头环绕", "action frozen mid-motion while the camera orbits"),
        },
    },
    "psychology": {
        "label": "心理放大",
        "purpose": "情绪进入脸与眼睛",
        "levels": {
            "strong": ("Zoom In", "eye_level", "slow", "缓慢推近至眼睛，瞳孔反光与情绪变化", "slow push to the eyes, reflections and emotion shifting"),
            "medium": ("Static", "eye_level", "slow", "固定窗边侧拍，柔光洒落，人物静止", "static side shot by the window, soft light, still figure"),
            "soft": ("Static", "high_angle", "slow", "固定镜头中背影慢慢远去，空间空下来", "locked frame, the back slowly walks away, space empties"),
        },
    },
    "detail": {
        "label": "细节叙事",
        "purpose": "由物件和局部承接剧情信息",
        "levels": {
            "strong": ("Pan Right", "eye_level", "slow", "从关键物件特写缓慢移到人物脸部", "slow move from the object close-up to the face"),
            "medium": ("Zoom In", "eye_level", "slow", "聚焦手部握物、松手或轻触", "close on the hand gripping, releasing or touching"),
            "soft": ("Static", "pov", "steady", "镜头藏在门边观察，前景虚化", "camera hidden by the door frame, foreground blurred"),
        },
    },
    "fantasy": {
        "label": "奇幻特效",
        "purpose": "仙侠、奇幻、赛博的氛围镜头",
        "levels": {
            "strong": ("Push In", "eye_level", "fast", "穿过霓虹街景或云层快速抵达人物", "flying through neon streets or clouds to the character"),
            "medium": ("Orbit", "eye_level", "slow", "花瓣、火焰或雪花环绕人物，镜头缓慢移动", "petals, flames or snow around the character, slow camera"),
            "soft": ("Tilt Up", "eye_level", "slow", "从水面倒影缓缓上移显露真实人物", "tilt up from the reflection to reveal the real figure"),
        },
    },
    "finale": {
        "label": "史诗收束",
        "purpose": "结尾的完整展示",
        "levels": {
            "strong": ("Orbit", "low_angle", "slow", "360 度环绕人物，完整展示动作、造型与场景", "360 orbit fully showing action, look and scene"),
            "medium": ("Pull Out", "eye_level", "slow", "从人物中心慢慢拉远到巨大环境", "slow pull out from the character to the vast environment"),
            "soft": ("Static", "eye_level", "slow", "固定远景，人物立于天地之间", "locked wide, the figure between earth and sky"),
        },
    },
}
INTENSITIES: tuple[tuple[str, str], ...] = (("strong", "强"), ("medium", "中"), ("soft", "弱"))
QUALITY_ZH = "电影级质感，细节丰富，自然运动，浅景深，运动模糊自然，稳定流畅"
QUALITY_EN = "cinematic lighting, film grain, shallow depth of field, natural motion blur, smooth, 4k"
NEGATIVE_EN = "static camera, no movement, locked frame, flat angle, flat lighting, no emotion"


class CameraRecipe(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    category_label: str
    intensity: str
    camera_motion: str
    camera_motion_label: str
    angle: str
    angle_label: str
    rhythm: str
    rhythm_label: str
    prompt_zh: str = Field(max_length=2000)
    prompt_en: str = Field(max_length=2000)
    negative: str = Field(max_length=500)
    provider_phrase: str = Field(max_length=200)


def recipe_catalog() -> list[dict[str, str]]:
    return [
        {"value": key, "label": entry["label"], "purpose": entry["purpose"]}
        for key, entry in RECIPE_CATEGORIES.items()
    ]


def compose_recipe(
    category: str,
    intensity: str = "medium",
    *,
    subject_action: str = "",
    environment: str = "",
    lighting: str = "",
    provider_family: str = "",
) -> CameraRecipe:
    entry = RECIPE_CATEGORIES.get(category)
    if entry is None:
        raise ValueError(f"未知运镜类别：{category}")
    level = intensity if intensity in entry["levels"] else "medium"
    move, angle, rhythm, zh_hint, en_hint = entry["levels"][level]
    canonical, _ = normalize_camera_motion(move)
    action_zh = subject_action.strip() or zh_hint
    env_zh = environment.strip() or "环境随镜头运动持续变化"
    light_zh = lighting.strip() or "光影随运动自然过渡"
    prompt_zh = (
        f"{render_camera_motion(canonical, provider_family)}，{_ANGLE_ZH[angle]}机位，{_RHYTHM_ZH[rhythm]}；"
        f"{action_zh}；{env_zh}；{light_zh}；{QUALITY_ZH}"
    )
    prompt_en = (
        f"{canonical.lower()} camera move, {_ANGLE_EN[angle]}, {_RHYTHM_EN[rhythm]}; "
        f"{en_hint}; {QUALITY_EN}"
    )
    return CameraRecipe(
        category=category,
        category_label=entry["label"],
        intensity=level,
        camera_motion=canonical,
        camera_motion_label=CAMERA_MOTION_LABELS[canonical],
        angle=angle,
        angle_label=_ANGLE_ZH[angle],
        rhythm=rhythm,
        rhythm_label=_RHYTHM_ZH[rhythm],
        prompt_zh=prompt_zh,
        prompt_en=prompt_en,
        negative=NEGATIVE_EN,
        provider_phrase=render_camera_motion(canonical, provider_family),
    )


def _angle_key(text: str) -> str:
    haystack = str(text or "")
    for key, zh, en in ANGLES:
        if zh in haystack or en in haystack.lower():
            return key
    return "eye_level"


def repeated_move_signature(previous: dict[str, Any], current: dict[str, Any]) -> str:
    """Empty when adjacent shots differ in at least one of move / angle / rhythm; else the shared signature.

    Rhythm is read from duration (≤3s fast, ≥6s slow) so a table without an
    explicit rhythm column still gets checked.
    """
    def signature(shot: dict[str, Any]) -> tuple[str, str, str]:
        move, _ = normalize_camera_motion(shot.get("motion"))
        angle = _angle_key(shot.get("angle"))
        seconds = shot.get("_seconds")
        rhythm = "fast" if seconds and seconds <= 3 else "slow" if seconds and seconds >= 6 else "steady"
        return move, angle, rhythm

    before, after = signature(previous), signature(current)
    if before == after and before[0] != "Static":
        return f"{CAMERA_MOTION_LABELS[after[0]]} / {_ANGLE_ZH[after[1]]} / {_RHYTHM_ZH.get(after[2], after[2])}"
    return ""
