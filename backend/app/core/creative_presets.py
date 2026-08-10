"""Callable, clean-room creative presets derived from the audited source capabilities."""

from __future__ import annotations

import re

from pydantic import BaseModel, Field


class CreativePreset(BaseModel):
    id: str
    name: str
    source_id: str
    purpose: str
    instructions: tuple[str, ...]


class CompiledCreativePrompt(BaseModel):
    preset_id: str
    source_id: str
    prompt: str
    required_gates: list[str] = Field(default_factory=list)


_PRESETS: tuple[CreativePreset, ...] = (
    CreativePreset(
        id="h3-prompt-writing", name="H3 通用视频提示词", source_id="minimax-h3-skills",
        purpose="把故事意图编译成 H3 可执行的镜头、表演、声音与参考素材指令。",
        instructions=("只描述可见、可听、可计时的事件", "明确主任务、镜头路径、表演节拍和原生音频"),
    ),
    CreativePreset(
        id="3d-animation-short", name="3D 动画短片", source_id="minimax-h3-skills",
        purpose="风格统一的角色驱动 3D 动画短片。",
        instructions=("锁定材质、比例、轮廓和渲染风格", "用分层景深与可复现的灯光方案维持空间连续"),
    ),
    CreativePreset(
        id="brand-promo", name="品牌宣传片", source_id="minimax-h3-skills",
        purpose="以产品价值和品牌识别为核心的短视频。",
        instructions=("先建立使用情境再揭示产品价值", "保持产品几何、商标位置和品牌色稳定"),
    ),
    CreativePreset(
        id="co-op-game-intro", name="合作游戏开场", source_id="minimax-h3-skills",
        purpose="建立角色、任务、威胁和协作关系的游戏式片头。",
        instructions=("清楚交代队伍站位和目标", "动作遵守屏幕方向与空间轴线"),
    ),
    CreativePreset(
        id="handdrawn-live", name="手绘真人融合", source_id="minimax-h3-skills",
        purpose="真人表演与手绘视觉元素自然融合。",
        instructions=("真人身份与皮肤质感优先保持", "手绘元素必须有明确附着面和交互时机"),
    ),
    CreativePreset(
        id="minimalist-product-ad", name="极简产品广告", source_id="minimax-h3-skills",
        purpose="用少量元素突出产品轮廓、材质与关键卖点。",
        instructions=("控制背景、道具与色彩数量", "用宏观镜头和材质高光展示真实物理细节"),
    ),
    CreativePreset(
        id="music-video-subtitle", name="音乐视频字幕", source_id="minimax-h3-skills",
        purpose="音乐节奏、画面节拍和安全字幕区域对齐。",
        instructions=("剪辑点对齐强拍与乐句边界", "字幕只给版式和时机，最终文字后期叠加"),
    ),
    CreativePreset(
        id="paper-collage-explainer", name="纸张拼贴解说", source_id="minimax-h3-skills",
        purpose="通过纸张拼贴和层次运动解释信息。",
        instructions=("每个信息层有稳定纸张材质与层级", "用遮挡、滑入和翻页建立因果顺序"),
    ),
    CreativePreset(
        id="papercraft-stop-motion", name="纸艺定格动画", source_id="minimax-h3-skills",
        purpose="具有手作纹理和逐格节奏的纸艺动画。",
        instructions=("保留切边、折痕和轻微逐格位移", "避免物体拓扑和比例在帧间漂移"),
    ),
    CreativePreset(
        id="narrative-breakdown", name="叙事拆解", source_id="short-drama-skills",
        purpose="从剧本提取目标、阻力、转折、悬念和镜头任务。",
        instructions=("每格只承担一个主要叙事功能", "按建立空间、人物关系、情绪推进组织镜头"),
    ),
    CreativePreset(
        id="deep-emotion", name="深层情绪与权力转移", source_id="short-drama-skills",
        purpose="把潜台词、权力转移和情绪节奏变成细腻表演。",
        instructions=("标注微表情、视线、停顿、呼吸和肌肉张力", "对话按情绪拍点分段并保留反应镜头"),
    ),
    CreativePreset(
        id="detailed-action", name="细节动作", source_id="short-drama-skills",
        purpose="把抽象动作改写成可拍摄的身体与道具动作链。",
        instructions=("动作写成准备、执行、接触、反应、恢复", "记录手别、道具位置和运动方向"),
    ),
    CreativePreset(
        id="episode-continuity", name="剧集连续性", source_id="short-drama-skills",
        purpose="维持跨镜头和跨集的人物、场景、道具、剧情状态。",
        instructions=("为每镜保存开始态和结束态", "延续服装、妆发、伤痕、道具、灯光和轴线"),
    ),
    CreativePreset(
        id="single-video-polish", name="单条视频精修", source_id="short-drama-skills",
        purpose="把单个镜头精修为时长内可执行的生成指令。",
        instructions=("限制镜头内事件数量", "逐秒安排镜头、动作、表情、对白和声音"),
    ),
    CreativePreset(
        id="high-impact-drama", name="高冲击短剧", source_id="short-drama-skills",
        purpose="强化冲突、反转、悬念钩子和反应镜头。",
        instructions=("冲击前留出信息和情绪蓄力", "反转后必须给人物可读的真实反应"),
    ),
    CreativePreset(
        id="slow-cinematic", name="慢节奏电影感", source_id="short-drama-skills",
        purpose="通过克制运镜、环境细节和细腻表演建立真人电影感。",
        instructions=("延长可读的停顿和反应而非空镜拖时", "优先自然皮肤、细微不对称和物理可信光线"),
    ),
    CreativePreset(
        id="sd25-pe-production", name="sd25-pe 生产编译", source_id="sd25-pe",
        purpose="按素材职责、关键帧和对话台账编译视频生成提示词。",
        instructions=("逐份声明参考素材的身份、外观、动作或声音职责", "分离主体、时序、镜头、声音和参数约束"),
    ),
)


_GLOBAL_GATES = (
    "建立角色、场景、道具、特效四类资产清单；每一格逐项声明使用或不使用，禁止未授权素材串入。",
    "每个角色先生成并验收角色五视图：正面、前四分之三、侧面、后四分之三、背面；身份 DNA、服装、比例一致。",
    "分镜必须输出物理 3×3 九宫格，严格 1—9 左到右、上到下；每格包含景别、机位、运镜、动作、微表情、对白、声音、时长及进出状态。",
    "镜头顺序先建立空间，再建立人物关系，再推进情绪；每镜明确叙事目的和剪辑落点。",
    "视频生成先选择唯一主模式：文本、首帧、尾帧、首尾帧或多模态参考；逐份定义多图、视频、音频素材职责。",
    "首帧必须精确承接上一镜尾态，尾帧必须形成下一镜可接状态；保持180度轴线、视线、动作方向、道具位置和光色连续。",
    "真人感门禁：自然皮肤纹理、正确解剖、手指与口型、细微不对称；表演写明视线、眨眼、呼吸、停顿、肌肉张力与情绪转折。",
    "对白建立角色声音、语速、重音、停顿和情绪弧台账；音乐、环境声、对白与转场音频按节拍衔接。",
    "合成长视频前检查身份、造型、空间、动作、光色、叙事和音频连续性；优先动作匹配、视线匹配、声音桥和受控交叉转场。",
)


class CreativePresetRegistry:
    def __init__(self) -> None:
        self._presets = {preset.id: preset for preset in _PRESETS}

    def list(self) -> list[CreativePreset]:
        return list(_PRESETS)

    def get(self, preset_id: str) -> CreativePreset:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,79}", preset_id or ""):
            raise KeyError(f"unknown creative preset: {preset_id}")
        try:
            return self._presets[preset_id]
        except KeyError as exc:
            raise KeyError(f"unknown creative preset: {preset_id}") from exc

    def compile(
        self,
        preset_id: str,
        content: str,
        *,
        asset_context: str = "",
        language: str = "zh-CN",
    ) -> CompiledCreativePrompt:
        preset = self.get(preset_id)
        clean_content = content.strip()
        if not clean_content:
            raise ValueError("content must not be empty")
        if len(clean_content) > 30000 or len(asset_context) > 20000:
            raise ValueError("creative input is too large")

        prompt = "\n".join(
            [
                f"创作模式：{preset.name}",
                f"目标：{preset.purpose}",
                f"输出语言：{language}",
                "模式规则：",
                *(f"- {rule}" for rule in preset.instructions),
                "不可省略的生产合同：",
                *(f"- {gate}" for gate in _GLOBAL_GATES),
                f"已批准资产上下文：{asset_context.strip() or '未提供；先建立资产清单，禁止自行假定参考素材。'}",
                "创作输入：",
                clean_content,
                "输出必须为结构化可执行方案，并在末尾给出逐项质量门禁与失败重试建议。",
            ]
        )
        return CompiledCreativePrompt(
            preset_id=preset.id,
            source_id=preset.source_id,
            prompt=prompt,
            required_gates=list(_GLOBAL_GATES),
        )

