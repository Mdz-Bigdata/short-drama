"""Deterministic capability compiler and fail-closed gate for all eight agents.

The supplied Markdown files are treated as reviewable production specifications.
They are never executed, imported, or trusted as code.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Final

from app.schema.agent_council import (
    ALL_AGENT_ROLES,
    AgentBlueprint,
    AgentHandoff,
    AgentRole,
    CapabilityRecord,
    CORE_SCORE_DIMENSIONS,
    CouncilCompileRequest,
    CouncilIssue,
    CouncilPlan,
    CouncilReleaseEvidence,
    CouncilReleaseReport,
    DeliveryProfile,
    KnowledgeSourceRecord,
    ProductionConstitution,
    ReleaseCheck,
)


PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]

KNOWLEDGE_SOURCE_FILES: Final[tuple[str, ...]] = (
    "AI 生成短剧一致性检查清单.md",
    "AI影视剧台词语速情绪提示词总结.md",
    "AI影视剧负面提示词.md",
    "AI漫剧短剧剧本黄金叙事结构.md",
    "AI短剧与漫剧导演级拍摄分镜完全指南.md",
    "AI短剧五视图解决人物一致性提示词模板.md",
    "AI短剧注意事项与关键元素.md",
    "AI短剧电影级武打镜头设计指南.md",
    "AI短剧表演细节与提示词指南.md",
    "AI短剧连续性设计指南.md",
    "SKILL.md",
    "THIRD_PARTY_NOTICES.md",
    "场景设计提示词.md",
    "影视剧高光时刻识别方案.md",
    "画质风格类型总结.md",
    "短剧情绪与面部表情提示词库.md",
    "短剧情节与镜头连贯性提示词.md",
    "短剧题材类型总结.md",
)


_ROLE_NAMES: Final[dict[AgentRole, tuple[str, str]]] = {
    AgentRole.EXECUTIVE_DIRECTOR: ("总导演", "Executive Director"),
    AgentRole.WRITER: ("编剧", "Writer Agent"),
    AgentRole.CHARACTER_DESIGNER: ("角色设计师", "Character Designer"),
    AgentRole.STORYBOARD_ARTIST: ("分镜师", "Storyboard Artist"),
    AgentRole.VISUAL_DIRECTOR: ("视觉总监", "Visual Director"),
    AgentRole.AUDIO_DIRECTOR: ("音频总监", "Audio Director"),
    AgentRole.COMPOSER_PUBLISHER: ("合成发布", "Composer & Publisher"),
    AgentRole.PR_AGENT: ("宣发 Agent", "PR Agent"),
}

_MISSIONS: Final[dict[AgentRole, str]] = {
    AgentRole.EXECUTIVE_DIRECTOR: "确立题材、受众、商业边界、叙事弧、高光与全局质量标准，并裁决跨部门冲突。",
    AgentRole.WRITER: "交付可拍、可听、因果完整的分集剧本，管理钩子、信息差、伏笔、弧光、台词与情绪节拍。",
    AgentRole.CHARACTER_DESIGNER: "锁定每个角色与状态的身份 DNA、严格五视图、造型、标志物、表演基线与声音身份。",
    AgentRole.STORYBOARD_ARTIST: "把剧本拆成连续可生成的时间拍点、九宫格、场景圣经、镜头契约、动作与剪辑交接。",
    AgentRole.VISUAL_DIRECTOR: "锁定画风、场景、光色材质与参考资产，编译负面词并自动路由多种视频生成模式。",
    AgentRole.AUDIO_DIRECTOR: "设计角色声卡、逐句语速情绪停顿、口型时序、SFX/Foley、BGM 与可编辑混音计划。",
    AgentRole.COMPOSER_PUBLISHER: "完成剪辑、转场、字幕、音画合成、母版、平台导出、版本归档与发布前验收。",
    AgentRole.PR_AGENT: "从真实高光中制作封面、标题、预告、文案、标签、A/B 计划、在地化与投放指标闭环。",
}

_ROLE_OUTPUTS: Final[dict[AgentRole, tuple[str, ...]]] = {
    AgentRole.EXECUTIVE_DIRECTOR: (
        "director_constitution", "genre_audience_strategy", "series_narrative_arc",
        "highlight_map", "production_risk_register", "director_approval",
    ),
    AgentRole.WRITER: (
        "series_bible", "episode_scripts", "character_arcs", "dialogue_sheet",
        "foreshadow_ledger", "writer_compliance_pass",
    ),
    AgentRole.CHARACTER_DESIGNER: (
        "character_bible", "five_view_turnarounds", "character_state_cards",
        "costume_makeup_ledger", "prop_ownership", "voice_identity_brief",
    ),
    AgentRole.STORYBOARD_ARTIST: (
        "scene_bibles", "exact_nine_grid_storyboards", "shot_motion_contracts",
        "continuity_ledger", "action_choreography", "storyboard_qc",
    ),
    AgentRole.VISUAL_DIRECTOR: (
        "visual_bible", "style_palette_lighting_lock", "negative_prompt_plan",
        "reference_binding_plan", "generated_keyframes", "video_route_plans", "visual_qc",
    ),
    AgentRole.AUDIO_DIRECTOR: (
        "voice_cards", "dialogue_timing", "elevenlabs_job_plan", "sfx_foley_cues",
        "bgm_music_plan", "lipsync_plan", "audio_mix_plan", "audio_qc",
    ),
    AgentRole.COMPOSER_PUBLISHER: (
        "edit_decision_list", "transition_plan", "subtitle_package", "mastered_timeline",
        "export_profiles", "delivery_archive", "final_qc",
    ),
    AgentRole.PR_AGENT: (
        "highlight_clips", "cover_title_variants", "trailer_plan", "platform_copy_tags",
        "ab_test_plan", "localization_package", "rights_ai_disclosure", "campaign_kpis",
    ),
}

_ROLE_GATES: Final[dict[AgentRole, tuple[str, ...]]] = {
    AgentRole.EXECUTIVE_DIRECTOR: (
        "前3秒有可见冲突/悬念；每集有冲突、情绪点和尾钩。",
        "题材、受众、平台、预算、合规和人类审批边界明确。",
        "所有高光有前文铺垫、强度、情绪、叙事功能和可传播依据。",
    ),
    AgentRole.WRITER: (
        "只写镜头可见与声音可听内容；不以心理旁白代替行动。",
        "每句台词默认不超过15个汉字，并标注潜台词、重音、停顿与打断。",
        "因果、人物知情状态、时间线、伏笔回收和多集承接均有台账。",
    ),
    AgentRole.CHARACTER_DESIGNER: (
        "每个角色/状态独立交付严格五视图，顺序不得改变且通过完整性检查。",
        "脸、发际线、体型、服装层次、配饰、伤痕与标志道具可量化且可复用。",
        "角色之间在脸型、发型、服装主色和声纹上可区分。",
    ),
    AgentRole.STORYBOARD_ARTIST: (
        "每页为严格3×3九宫格，逐格包含角色、场景、道具、特效与完整镜头字段。",
        "每镜只推进一个动作/信息/情绪节拍，并承接上一镜首尾状态。",
        "轴线、视线、左右站位、光向、道具归属和声音桥连续；动作戏拆成出招/受击/环境反馈。",
    ),
    AgentRole.VISUAL_DIRECTOR: (
        "分镜图提示词与运镜提示词来自同一 ShotMotionContract，指纹一致。",
        "首尾帧、多图/宫格、多模态模式由素材与供应商能力自动选择，缺失能力必须失败关闭。",
        "负面词按人物/手部/多人/场景/材质/时序/题材模块选择，不盲目堆叠。",
    ),
    AgentRole.AUDIO_DIRECTOR: (
        "同一角色固定 voice_id/声纹；逐句记录语速、情绪、停顿、重音、呼吸与时长。",
        "对白、环境、动作、情绪、Foley、BGM 均在同一时间轴，撞击音效帧级对齐。",
        "ElevenLabs 密钥仅从服务端环境读取；SFX 使用 /v1/sound-generation，音乐与配音使用各自端点。",
    ),
    AgentRole.COMPOSER_PUBLISHER: (
        "音画、字幕、口型、镜头契约与转场连续性全部通过，未验收素材不得发布。",
        "输出分辨率/帧率/编码/字幕安全区按目标平台统一，不混用互斥基准。",
        "保留提示词、模型、seed、素材授权、版本、问题与审批记录，支持单镜重做。",
    ),
    AgentRole.PR_AGENT: (
        "宣传素材只能取自正片真实高光，不得夸大或诱导。",
        "每个平台独立交付封面、标题、预告、简介、标签、AI标识与版权说明。",
        "用3秒留存、完播、下一集点击、转化、分享和ROI做A/B闭环。",
    ),
}


def _cap(
    capability_id: str,
    label: str,
    owners: tuple[AgentRole, ...],
    sources: tuple[str, ...],
    policy: str,
    validator: str,
    artifacts: tuple[str, ...],
) -> CapabilityRecord:
    return CapabilityRecord(
        id=capability_id,
        label=label,
        owners=list(owners),
        source_files=list(sources),
        executable_policy=policy,
        validator=validator,
        required_artifacts=list(artifacts),
    )


_C = AgentRole
CAPABILITIES: Final[tuple[CapabilityRecord, ...]] = (
    _cap("genre_strategy", "题材、受众与商业定位", (_C.EXECUTIVE_DIRECTOR, _C.PR_AGENT),
         ("短剧题材类型总结.md", "AI短剧注意事项与关键元素.md", "SKILL.md"),
         "从题材库选择主类型/混合元素，记录受众、平台、付费与成本边界。", "validate_director_artifacts", ("genre_audience_strategy",)),
    _cap("golden_narrative", "黄金叙事结构与多集弧", (_C.EXECUTIVE_DIRECTOR, _C.WRITER),
         ("AI漫剧短剧剧本黄金叙事结构.md", "AI短剧注意事项与关键元素.md"),
         "强制前3秒钩子、周期冲突/反转、单集情绪点与尾5秒钩子。", "validate_narrative_contract", ("series_narrative_arc", "episode_scripts")),
    _cap("highlight_detection", "高光识别与传播强度", (_C.EXECUTIVE_DIRECTOR, _C.PR_AGENT),
         ("影视剧高光时刻识别方案.md",),
         "按情节/情绪/叙事/视听/观众行为打1-10分，7分以上进入候选并保留上下文理由。", "validate_highlight_map", ("highlight_map", "highlight_clips")),
    _cap("production_orchestration", "八 Agent 编排与人类审批", (_C.EXECUTIVE_DIRECTOR,),
         ("SKILL.md", "AI 生成短剧一致性检查清单.md"),
         "八角色按契约交接；缺失输入、未批准资产或阻断问题不得向下游推进。", "validate_council_coverage", ("director_constitution", "director_approval")),
    _cap("story_causality", "因果、信息状态、伏笔与世界规则", (_C.WRITER, _C.EXECUTIVE_DIRECTOR),
         ("AI 生成短剧一致性检查清单.md", "AI漫剧短剧剧本黄金叙事结构.md"),
         "维护因果链、角色知情表、世界规则、时间线、伏笔设置/回收和关系变化台账。", "validate_narrative_contract", ("series_bible", "foreshadow_ledger")),
    _cap("dialogue_craft", "口语台词、潜台词与角色辨识", (_C.WRITER, _C.AUDIO_DIRECTOR),
         ("AI影视剧台词语速情绪提示词总结.md", "AI短剧注意事项与关键元素.md"),
         "台词短句化并记录角色语癖、潜台词、打断/重叠、叙述层与可读时长。", "validate_dialogue_contract", ("dialogue_sheet", "voice_cards")),
    _cap("dialogue_performance", "语速、情绪、停顿、重音与呼吸", (_C.AUDIO_DIRECTOR, _C.WRITER),
         ("AI影视剧台词语速情绪提示词总结.md", "AI短剧表演细节与提示词指南.md"),
         "逐句编译 speed/emotion/intensity/pause/stress/breath，并校验对白时长与镜头时长。", "validate_audio_contract", ("dialogue_timing", "lipsync_plan")),
    _cap("five_view_identity", "角色五视图与身份 DNA", (_C.CHARACTER_DESIGNER,),
         ("AI短剧五视图解决人物一致性提示词模板.md", "AI 生成短剧一致性检查清单.md"),
         "每个角色状态严格按正面/正面四分之三/侧面/背面四分之三/背面生成并质检。", "validate_five_view_contract", ("five_view_turnarounds", "character_state_cards")),
    _cap("character_styling", "发型、服化、体型、标志物与状态版本", (_C.CHARACTER_DESIGNER, _C.VISUAL_DIRECTOR),
         ("AI短剧五视图解决人物一致性提示词模板.md", "AI短剧与漫剧导演级拍摄分镜完全指南.md"),
         "造型字段逐项锁定；换装/战损/年龄变化使用新 state_id，不覆盖基础状态。", "validate_character_artifacts", ("character_bible", "costume_makeup_ledger")),
    _cap("observable_acting", "可观察表演与微表情", (_C.CHARACTER_DESIGNER, _C.STORYBOARD_ARTIST, _C.VISUAL_DIRECTOR),
         ("AI短剧表演细节与提示词指南.md", "短剧情绪与面部表情提示词库.md", "AI短剧电影级武打镜头设计指南.md"),
         "把抽象情绪转换为眉眼嘴颌、视线、呼吸、手部、重心和渐进关键帧。", "validate_performance_contract", ("character_bible", "shot_motion_contracts", "visual_qc")),
    _cap("scene_bible", "功能化场景圣经", (_C.STORYBOARD_ARTIST, _C.VISUAL_DIRECTOR),
         ("场景设计提示词.md", "AI短剧连续性设计指南.md"),
         "为场景锁定剧情功能、布局、出入口、站位、关键道具、光向色温、材质与前中后景。", "validate_scene_contract", ("scene_bibles", "visual_bible")),
    _cap("shot_grammar", "景别、构图、机位、焦段与运镜语法", (_C.STORYBOARD_ARTIST,),
         ("AI短剧与漫剧导演级拍摄分镜完全指南.md", "画质风格类型总结.md"),
         "每镜说明景别/角度/焦段/构图/运镜路径/速度/起止点/叙事原因，禁止无动机炫技。", "validate_storyboard_contract", ("shot_motion_contracts",)),
    _cap("blocking_axis", "站位、视线与180度轴线", (_C.STORYBOARD_ARTIST, _C.VISUAL_DIRECTOR),
         ("AI短剧与漫剧导演级拍摄分镜完全指南.md", "AI短剧连续性设计指南.md"),
         "固定角色左右、眼线、动作方向和机位侧；跨轴须有可见过轴或中性镜头。", "validate_continuity_contract", ("continuity_ledger", "reference_binding_plan")),
    _cap("exact_nine_grid", "严格九宫格与分页", (_C.STORYBOARD_ARTIST,),
         ("AI短剧五视图解决人物一致性提示词模板.md", "短剧情节与镜头连贯性提示词.md"),
         "分镜按3×3从左到右、从上到下；每格一拍，真实镜不足时只留空格不伪造剧情。", "validate_nine_grid_contract", ("exact_nine_grid_storyboards", "storyboard_qc")),
    _cap("continuity_six_anchors", "跨镜六锚点连续性", (_C.STORYBOARD_ARTIST, _C.VISUAL_DIRECTOR, _C.COMPOSER_PUBLISHER),
         ("短剧情节与镜头连贯性提示词.md", "AI短剧连续性设计指南.md", "AI 生成短剧一致性检查清单.md"),
         "人物/空间/动作/情绪/道具/光影从上一镜尾状态原样交付下一镜首状态。", "validate_continuity_contract", ("continuity_ledger", "transition_plan")),
    _cap("fight_choreography", "武打力学与出招-受击拆分", (_C.STORYBOARD_ARTIST, _C.VISUAL_DIRECTOR, _C.AUDIO_DIRECTOR),
         ("AI短剧电影级武打镜头设计指南.md",),
         "高风险动作拆为蓄力/出招/受击/环境反馈，单镜1.5-2.5秒并对齐冲击帧、SFX与轴线。", "validate_action_contract", ("action_choreography", "sfx_foley_cues")),
    _cap("visual_style", "画质、载体、色彩、光影与材质风格", (_C.VISUAL_DIRECTOR, _C.EXECUTIVE_DIRECTOR),
         ("画质风格类型总结.md", "AI短剧与漫剧导演级拍摄分镜完全指南.md"),
         "按题材/载体选择唯一视觉基线并锁定色板、LUT、主光、镜头质感和材质。", "validate_visual_contract", ("style_palette_lighting_lock",)),
    _cap("negative_prompt_router", "模块化负面提示词", (_C.VISUAL_DIRECTOR,),
         ("AI影视剧负面提示词.md", "短剧情绪与面部表情提示词库.md"),
         "按任务与题材选择通用/脸/手/多人/服装/场景/材质/时序/表演模块，保留优先级。", "validate_visual_contract", ("negative_prompt_plan",)),
    _cap("reference_generation", "多图、首尾帧与多模态视频路由", (_C.VISUAL_DIRECTOR, _C.STORYBOARD_ARTIST),
         ("AI短剧五视图解决人物一致性提示词模板.md", "AI短剧连续性设计指南.md", "SKILL.md"),
         "根据硬结尾、连续图片、动作视频、音频节奏和供应商能力自动选择模式；不静默丢参考。", "validate_video_route_contract", ("video_route_plans", "reference_binding_plan")),
    _cap("prompt_fingerprint", "分镜图与运镜同源契约", (_C.STORYBOARD_ARTIST, _C.VISUAL_DIRECTOR),
         ("AI短剧五视图解决人物一致性提示词模板.md",),
         "分镜图和视频提示词必须携带同一规范化 ShotMotionContract 指纹；变更使旧计划失效。", "validate_fingerprint_contract", ("shot_motion_contracts", "generated_keyframes")),
    _cap("visual_quality_repair", "视觉质检与局部修复", (_C.VISUAL_DIRECTOR, _C.COMPOSER_PUBLISHER),
         ("AI 生成短剧一致性检查清单.md", "AI短剧表演细节与提示词指南.md", "AI短剧注意事项与关键元素.md"),
         "检测身份漂移、手部、口型、闪烁、光向、文字和物理异常；仅重做失败镜头/区域。", "validate_visual_contract", ("visual_qc", "final_qc")),
    _cap("elevenlabs_audio", "ElevenLabs 配音、对白、SFX与音乐", (_C.AUDIO_DIRECTOR,),
         ("AI影视剧台词语速情绪提示词总结.md", "AI短剧注意事项与关键元素.md", "SKILL.md"),
         "生成可审计服务端任务计划；密钥来自环境，SFX/BGM/TTS端点分离且不在日志暴露。", "validate_audio_contract", ("elevenlabs_job_plan",)),
    _cap("voice_identity", "角色声卡与声纹连续", (_C.AUDIO_DIRECTOR, _C.CHARACTER_DESIGNER),
         ("AI影视剧台词语速情绪提示词总结.md", "AI短剧表演细节与提示词指南.md"),
         "角色固定 voice_id、音高、年龄感、语癖、语速基准与授权引用，情绪仅做受控偏移。", "validate_audio_contract", ("voice_cards", "voice_identity_brief")),
    _cap("sfx_bgm_mix", "环境音、Foley、BGM与混音母版", (_C.AUDIO_DIRECTOR, _C.COMPOSER_PUBLISHER),
         ("AI短剧注意事项与关键元素.md", "AI短剧电影级武打镜头设计指南.md", "AI短剧连续性设计指南.md"),
         "环境床跨镜连续、动作声帧对齐、对白时BGM ducking，并交付响度/真峰值母版计划。", "validate_audio_contract", ("sfx_foley_cues", "bgm_music_plan", "audio_mix_plan")),
    _cap("lip_sync", "口型、字幕与对白时序", (_C.AUDIO_DIRECTOR, _C.COMPOSER_PUBLISHER),
         ("AI短剧表演细节与提示词指南.md", "AI影视剧台词语速情绪提示词总结.md"),
         "先锁最终干声，再生成口型与逐字时间戳；字幕、闭口手柄与镜头时长共同校验。", "validate_lipsync_contract", ("lipsync_plan", "subtitle_package")),
    _cap("editing_transitions", "剪辑节奏与连续性转场", (_C.COMPOSER_PUBLISHER, _C.STORYBOARD_ARTIST),
         ("AI短剧连续性设计指南.md", "AI短剧注意事项与关键元素.md", "AI短剧与漫剧导演级拍摄分镜完全指南.md"),
         "同场优先硬切，时间跳跃用叠化，差异用遮挡/运动/匹配剪辑；转场必须有叙事原因。", "validate_delivery_contract", ("edit_decision_list", "transition_plan")),
    _cap("delivery_master", "字幕、画幅、帧率、编码与归档", (_C.COMPOSER_PUBLISHER,),
         ("AI短剧注意事项与关键元素.md", "画质风格类型总结.md", "AI 生成短剧一致性检查清单.md"),
         "按单一目标平台编译导出配置，校验字幕安全区、OCR、音量、帧率、分辨率、命名、版本与元数据。", "validate_delivery_contract", ("mastered_timeline", "export_profiles", "delivery_archive")),
    _cap("release_gate", "S/A/B/C 一致性发布门禁", (_C.EXECUTIVE_DIRECTOR, _C.COMPOSER_PUBLISHER),
         ("AI 生成短剧一致性检查清单.md",),
         "未解决S/A为0、B不超过3、核心均分至少4/5、总分至少85且所有硬门禁通过才可发布。", "evaluate_release", ("final_qc", "director_approval")),
    _cap("marketing_package", "封面、标题、预告、文案与标签", (_C.PR_AGENT,),
         ("影视剧高光时刻识别方案.md", "AI短剧注意事项与关键元素.md", "SKILL.md"),
         "从已批准高光生成平台化素材，保留正片事实、角色状态、视觉风格和合规边界。", "validate_marketing_contract", ("cover_title_variants", "trailer_plan", "platform_copy_tags")),
    _cap("growth_loop", "平台指标、A/B、投流与商业闭环", (_C.PR_AGENT, _C.EXECUTIVE_DIRECTOR),
         ("AI短剧注意事项与关键元素.md", "短剧题材类型总结.md"),
         "跟踪3秒留存、完播、下一集点击、付费、分享和ROI，结论回写下一轮创作假设。", "validate_marketing_contract", ("ab_test_plan", "campaign_kpis")),
    _cap("rights_provenance", "授权、版权、AI标识与第三方溯源", (_C.PR_AGENT, _C.COMPOSER_PUBLISHER, _C.EXECUTIVE_DIRECTOR),
         ("THIRD_PARTY_NOTICES.md", "AI短剧注意事项与关键元素.md", "AI 生成短剧一致性检查清单.md"),
         "记录人类创作参与、素材/声纹授权、模型条款、来源、AI标识、版本与审批，不复制受限代码资产。", "validate_provenance_contract", ("rights_ai_disclosure", "delivery_archive", "production_risk_register")),
)


_VALIDATORS: Final[frozenset[str]] = frozenset({
    "validate_director_artifacts", "validate_narrative_contract", "validate_highlight_map",
    "validate_council_coverage", "validate_dialogue_contract", "validate_audio_contract",
    "validate_five_view_contract", "validate_character_artifacts", "validate_performance_contract",
    "validate_scene_contract", "validate_storyboard_contract", "validate_continuity_contract",
    "validate_nine_grid_contract", "validate_action_contract", "validate_visual_contract",
    "validate_video_route_contract", "validate_fingerprint_contract", "validate_lipsync_contract",
    "validate_delivery_contract", "evaluate_release", "validate_marketing_contract",
    "validate_provenance_contract",
})


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fingerprint(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _delivery_profile(platform: str) -> DeliveryProfile:
    if platform == "bilibili":
        return DeliveryProfile(
            aspect_ratio="16:9", width=1920, height=1080, fps=24,
            subtitle_safe_zone="下方10%，避开画面边缘与播放器控件",
        )
    return DeliveryProfile(
        aspect_ratio="9:16", width=1080, height=1920, fps=30,
        subtitle_safe_zone="字幕位于下方1/5上沿；避开顶部约200px与底部约250px平台UI",
    )


def _negative_modules(request: CouncilCompileRequest) -> list[str]:
    modules = [
        "common_quality", "face_anatomy", "hands_body", "identity_outfit",
        "scene_layout_lighting", "temporal_continuity", "text_watermark",
    ]
    genre = request.genre.lower()
    if any(word in genre for word in ("古", "宫", "武侠", "仙侠", "period", "wuxia", "xianxia")):
        modules.append("period_costume_architecture")
    if any(word in genre for word in ("悬疑", "犯罪", "恐怖", "mystery", "crime", "horror")):
        modules.append("suspense_horror_visibility")
    if any(word in genre for word in ("科幻", "赛博", "sci", "cyber")):
        modules.append("scifi_material_ui")
    if request.action_intensity == "high":
        modules.extend(["action_physics", "weapon_contact", "crowd_limb_separation"])
    return modules


def _source_records() -> list[KnowledgeSourceRecord]:
    capability_ids_by_source: dict[str, list[str]] = {name: [] for name in KNOWLEDGE_SOURCE_FILES}
    for capability in CAPABILITIES:
        for filename in capability.source_files:
            if filename not in capability_ids_by_source:
                raise RuntimeError(f"unknown knowledge source in capability catalog: {filename}")
            capability_ids_by_source[filename].append(capability.id)

    records: list[KnowledgeSourceRecord] = []
    for filename in KNOWLEDGE_SOURCE_FILES:
        path = PROJECT_ROOT / filename
        if not path.is_file():
            raise RuntimeError(f"required production knowledge source is missing: {filename}")
        data = path.read_bytes()
        records.append(KnowledgeSourceRecord(
            filename=filename,
            project_relative_path=filename,
            sha256=hashlib.sha256(data).hexdigest(),
            byte_size=len(data),
            capability_ids=sorted(capability_ids_by_source[filename]),
        ))
    return records


def _role_capabilities(role: AgentRole) -> list[CapabilityRecord]:
    return [capability for capability in CAPABILITIES if role in capability.owners]


def _role_prompt(
    role: AgentRole,
    request: CouncilCompileRequest,
    delivery: DeliveryProfile,
    constitution: ProductionConstitution,
) -> str:
    name_zh, name_en = _ROLE_NAMES[role]
    capabilities = _role_capabilities(role)
    policies = "\n".join(f"- [{item.id}] {item.executable_policy}" for item in capabilities)
    outputs = "、".join(_ROLE_OUTPUTS[role])
    gates = "\n".join(f"- {gate}" for gate in _ROLE_GATES[role])
    return (
        f"Role: {name_zh} ({name_en})\n"
        f"项目：《{request.title}》；题材={request.genre}；受众={request.audience}；平台={request.platform}；"
        f"形式={request.format}；语言={request.output_language}。\n"
        f"使命：{_MISSIONS[role]}\n"
        "共同硬约束：角色使用严格五视图；分镜使用3×3九宫格；角色/场景/道具/特效不可省略；"
        "分镜图与运镜必须同源并校验契约指纹；视频路由必须在首尾帧、多图/宫格、多模态与首帧模式中按能力自动选择；"
        "不支持的输入不得静默丢弃；任何密钥不得写入提示词、前端、日志或产物。\n"
        f"交付基准：{delivery.width}×{delivery.height} {delivery.aspect_ratio} {delivery.fps}fps；"
        f"前{constitution.opening_hook_deadline_seconds:g}秒钩子；对白默认不超过"
        f"{constitution.dialogue_max_han_characters}个汉字；发布阈值{constitution.release_threshold}分；"
        "执行 S/A/B/C 问题分级门禁。\n"
        f"本角色可执行能力：\n{policies}\n"
        f"必须交付的结构化 artifact_id：{outputs}。\n"
        f"本阶段验收：\n{gates}\n"
        "输出必须显式列出输入来源、假设、结构化交付物、未解决风险、交接对象和验收结论；"
        "缺少关键输入时标记 BLOCKED，不得伪造已生成、已授权或已验收。"
    )


def _handoffs() -> list[AgentHandoff]:
    pairs = list(zip(ALL_AGENT_ROLES, ALL_AGENT_ROLES[1:]))
    handoffs = [
        AgentHandoff(
            producer=producer,
            consumer=consumer,
            required_artifacts=list(_ROLE_OUTPUTS[producer]),
            acceptance_rules=[
                "artifact_id 完整且版本/来源/审批状态可追踪",
                "消费者需要的角色、场景、道具、特效与连续性字段不得为空",
                "未解决 S/A 级问题不得交接",
            ],
        )
        for producer, consumer in pairs
    ]
    handoffs.append(AgentHandoff(
        producer=AgentRole.PR_AGENT,
        consumer=AgentRole.EXECUTIVE_DIRECTOR,
        required_artifacts=["rights_ai_disclosure", "campaign_kpis", "highlight_clips"],
        acceptance_rules=[
            "宣发主张与已批准正片高光一致",
            "版权、授权、AI标识、平台合规和最终人工复核齐备",
            "发布门禁可复算且所有阻断项为零",
        ],
    ))
    return handoffs


class AgentCouncilCompiler:
    """Compile role briefs and evaluate complete production evidence."""

    @staticmethod
    def _assert_catalog() -> None:
        ids = [capability.id for capability in CAPABILITIES]
        if len(ids) != len(set(ids)):
            raise RuntimeError("capability IDs must be unique")
        if any(capability.validator not in _VALIDATORS for capability in CAPABILITIES):
            raise RuntimeError("capability catalog references an unknown validator")
        uncovered_roles = [role.value for role in ALL_AGENT_ROLES if not _role_capabilities(role)]
        if uncovered_roles:
            raise RuntimeError(f"agents without capabilities: {uncovered_roles}")

    def catalog(self) -> dict:
        self._assert_catalog()
        sources = _source_records()
        return {
            "agent_count": len(ALL_AGENT_ROLES),
            "source_count": len(sources),
            "capability_count": len(CAPABILITIES),
            "roles": [
                {
                    "stage": stage,
                    "role": role.value,
                    "name_zh": _ROLE_NAMES[role][0],
                    "name_en": _ROLE_NAMES[role][1],
                    "mission": _MISSIONS[role],
                    "capability_ids": [item.id for item in _role_capabilities(role)],
                    "required_outputs": list(_ROLE_OUTPUTS[role]),
                }
                for stage, role in enumerate(ALL_AGENT_ROLES, start=1)
            ],
            "sources": [record.model_dump() for record in sources],
            "capabilities": [record.model_dump(mode="json") for record in CAPABILITIES],
        }

    def compile(self, request: CouncilCompileRequest) -> CouncilPlan:
        self._assert_catalog()
        delivery = _delivery_profile(request.platform)
        vertical = delivery.aspect_ratio == "9:16"
        constitution = ProductionConstitution(
            reversal_interval_seconds=(15, 30) if vertical else (30, 60),
            shot_duration_seconds=(1.5, 4.0) if vertical else (3.0, 6.0),
        )
        source_records = _source_records()
        agents: list[AgentBlueprint] = []
        previous_outputs: list[str] = ["creator_brief", "premise", "platform_constraints"]
        for stage, role in enumerate(ALL_AGENT_ROLES, start=1):
            capabilities = _role_capabilities(role)
            outputs = list(_ROLE_OUTPUTS[role])
            agents.append(AgentBlueprint(
                stage=stage,
                role=role,
                name_zh=_ROLE_NAMES[role][0],
                name_en=_ROLE_NAMES[role][1],
                mission=_MISSIONS[role],
                capability_ids=[item.id for item in capabilities],
                knowledge_sources=sorted({source for item in capabilities for source in item.source_files}),
                required_inputs=previous_outputs,
                required_outputs=outputs,
                quality_gates=list(_ROLE_GATES[role]),
                handoff_to=([ALL_AGENT_ROLES[stage]] if stage < len(ALL_AGENT_ROLES) else [AgentRole.EXECUTIVE_DIRECTOR]),
                system_prompt=_role_prompt(role, request, delivery, constitution),
            ))
            previous_outputs = outputs

        request_fingerprint = _fingerprint(request.model_dump(mode="json"))
        all_sources_mapped = all(record.capability_ids for record in source_records)
        all_capabilities_owned = all(capability.owners for capability in CAPABILITIES)
        return CouncilPlan(
            plan_id=f"council_{request_fingerprint[:20]}",
            request_fingerprint=request_fingerprint,
            request=request,
            delivery=delivery,
            constitution=constitution,
            negative_prompt_modules=_negative_modules(request),
            agents=agents,
            handoffs=_handoffs(),
            source_records=source_records,
            capabilities=list(CAPABILITIES),
            coverage={
                "agent_count": len(agents),
                "source_count": len(source_records),
                "capability_count": len(CAPABILITIES),
                "all_sources_mapped": all_sources_mapped,
                "all_capabilities_owned": all_capabilities_owned,
            },
        )

    @staticmethod
    def evaluate_release(evidence: CouncilReleaseEvidence) -> CouncilReleaseReport:
        checks: list[ReleaseCheck] = []
        by_role: dict[AgentRole, set[str]] = {}
        approvals: dict[AgentRole, bool] = {}
        duplicate_roles: set[AgentRole] = set()
        for artifact in evidence.artifacts:
            if artifact.role in by_role:
                duplicate_roles.add(artifact.role)
            by_role.setdefault(artifact.role, set()).update(artifact.artifact_ids)
            approvals[artifact.role] = approvals.get(artifact.role, True) and artifact.approved

        checks.append(ReleaseCheck(
            code="council.roles_unique",
            passed=not duplicate_roles,
            detail="每个 Agent 只有一份权威验收记录" if not duplicate_roles else f"重复角色：{sorted(role.value for role in duplicate_roles)}",
            owner=AgentRole.EXECUTIVE_DIRECTOR,
        ))

        missing_artifacts: dict[str, list[str]] = {}
        for role in ALL_AGENT_ROLES:
            missing = sorted(set(_ROLE_OUTPUTS[role]) - by_role.get(role, set()))
            if missing:
                missing_artifacts[role.value] = missing
            present = role in by_role and not missing
            checks.append(ReleaseCheck(
                code=f"agent.{role.value}.artifacts",
                passed=present,
                detail="交付物完整" if present else f"缺失：{missing or ['整阶段证据']}",
                owner=role,
            ))
            approved = approvals.get(role, False)
            checks.append(ReleaseCheck(
                code=f"agent.{role.value}.approved",
                passed=approved,
                detail="阶段已批准" if approved else "阶段尚未批准",
                owner=role,
            ))

        expected_views = ["front", "front_three_quarter", "profile", "rear_three_quarter", "back"]
        structural = (
            ("character.five_view_order", evidence.five_view_order == expected_views,
             "五视图顺序正确" if evidence.five_view_order == expected_views else "五视图缺失或顺序错误", AgentRole.CHARACTER_DESIGNER),
            ("storyboard.exact_nine_grid", evidence.storyboard_rows == 3 and evidence.storyboard_columns == 3 and evidence.storyboard_panel_count == 9,
             f"{evidence.storyboard_rows}×{evidence.storyboard_columns}, panels={evidence.storyboard_panel_count}", AgentRole.STORYBOARD_ARTIST),
            ("storyboard.motion_fingerprint", evidence.storyboard_motion_fingerprints_match,
             "分镜与运镜契约指纹一致" if evidence.storyboard_motion_fingerprints_match else "契约指纹不一致", AgentRole.VISUAL_DIRECTOR),
            ("video.route_accepted", evidence.video_route_accepted and not evidence.unsupported_references_dropped,
             "视频路由已验收且未丢弃参考" if evidence.video_route_accepted and not evidence.unsupported_references_dropped else "视频路由未验收或静默丢弃参考", AgentRole.VISUAL_DIRECTOR),
            ("audio.dialogue_timing", evidence.dialogue_timing_approved, "对白时序已批准" if evidence.dialogue_timing_approved else "对白时序未批准", AgentRole.AUDIO_DIRECTOR),
            ("audio.mix", evidence.audio_mix_approved, "混音已批准" if evidence.audio_mix_approved else "混音未批准", AgentRole.AUDIO_DIRECTOR),
            ("delivery.final_media", evidence.final_media_present, "最终媒体存在" if evidence.final_media_present else "最终媒体缺失", AgentRole.COMPOSER_PUBLISHER),
            ("delivery.subtitles", evidence.subtitles_approved, "字幕已批准" if evidence.subtitles_approved else "字幕未批准", AgentRole.COMPOSER_PUBLISHER),
            ("compliance.rights_provenance", evidence.rights_and_provenance_approved,
             "授权与溯源已批准" if evidence.rights_and_provenance_approved else "授权或溯源未批准", AgentRole.PR_AGENT),
            ("compliance.platform", evidence.platform_compliance_approved,
             "平台合规已批准" if evidence.platform_compliance_approved else "平台合规未批准", AgentRole.PR_AGENT),
            ("review.human_final", evidence.human_final_review,
             "最终人工复核已完成" if evidence.human_final_review else "缺少最终人工复核", AgentRole.EXECUTIVE_DIRECTOR),
        )
        checks.extend(ReleaseCheck(code=code, passed=passed, detail=detail, owner=owner) for code, passed, detail, owner in structural)

        unresolved = [issue for issue in evidence.issues if not issue.resolved]
        severity_counts = {severity: sum(issue.severity == severity for issue in unresolved) for severity in ("S", "A", "B", "C")}
        severity_rules = (
            ("issues.no_unresolved_s", severity_counts["S"] == 0, "未解决S级问题必须为0"),
            ("issues.no_unresolved_a", severity_counts["A"] == 0, "未解决A级问题必须为0"),
            ("issues.b_within_limit", severity_counts["B"] <= 3, f"未解决B级问题={severity_counts['B']}，上限=3"),
        )
        checks.extend(ReleaseCheck(code=code, passed=passed, detail=detail, owner=AgentRole.EXECUTIVE_DIRECTOR) for code, passed, detail in severity_rules)

        core_scores = [evidence.dimension_scores[name] for name in CORE_SCORE_DIMENSIONS]
        core_average = round(sum(core_scores) / len(core_scores), 4)
        total_score = round(core_average / 5 * 100, 2)
        checks.extend([
            ReleaseCheck(
                code="score.core_average", passed=core_average >= 4.0,
                detail=f"核心均分={core_average}/5，最低=4.0", owner=AgentRole.EXECUTIVE_DIRECTOR,
            ),
            ReleaseCheck(
                code="score.total", passed=total_score >= 85,
                detail=f"总分={total_score}/100，最低=85", owner=AgentRole.EXECUTIVE_DIRECTOR,
            ),
        ])

        blocking_codes = [check.code for check in checks if not check.passed]
        return CouncilReleaseReport(
            releasable=not blocking_codes,
            total_score=total_score,
            core_average=core_average,
            severity_counts=severity_counts,
            checks=checks,
            blocking_codes=blocking_codes,
            missing_artifacts=missing_artifacts,
            evidence_fingerprint=_fingerprint(evidence.model_dump(mode="json")),
        )

    @staticmethod
    def unresolved_issue_summary(issues: list[CouncilIssue]) -> dict[str, list[str]]:
        summary = {role.value: [] for role in ALL_AGENT_ROLES}
        for issue in issues:
            if not issue.resolved:
                summary[issue.owner.value].append(f"[{issue.severity}] {issue.code}: {issue.detail}")
        return {role: records for role, records in summary.items() if records}
