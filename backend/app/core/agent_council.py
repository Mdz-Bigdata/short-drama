"""Deterministic capability compiler and fail-closed gate for all eight agents.

The supplied Markdown files are treated as reviewable production specifications.
They are never executed, imported, or trusted as code.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Final

from app.schema.agent_council import (
    ALL_AGENT_ROLES,
    POST_WRITER_ROLES,
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
from app.core import knowledge_registry, prompt_data
from app.schema.production import identity_view_order_is_valid


def knowledge_source_keys() -> tuple[str, ...]:
    """Every production-knowledge section the skills register; what the council fingerprints."""
    return tuple(sorted(knowledge_registry.sections()))


# The council's sentences, role prompts and word tables: app/data/prompt/agent_council.json.
_WORDING = "agent_council"


def _entry(key: str) -> Any:
    """The entry at the dotted ``key`` ("section.name") of the wording table."""
    node: Any = prompt_data.load(_WORDING)
    for part in key.split("."):
        node = node[part]
    return node


def _template(key: str) -> str:
    """A template of the wording table as written (an array of lines is joined with newlines)."""
    entry = _entry(key)
    return "\n".join(str(line) for line in entry) if isinstance(entry, list) else str(entry)


def _says(key: str, /, **values: object) -> str:
    """A template of the wording table, filled in (``key`` is positional: a template may name a ``{key}``)."""
    return _template(key).format(**values)


def _table(key: str) -> Any:
    """A word table or a list of rules of the wording table, used as it stands."""
    return _entry(key)


def _by_role(key: str) -> dict[AgentRole, Any]:
    """A table of the wording file keyed by ``AgentRole`` value, in the file's (stage) order."""
    return {AgentRole(role): value for role, value in _table(key).items()}


# 声音与成片合成是同一个角色「剪辑合成师」的两步：内部仍是第 6、7 阶段，各有各的交付物。
_ROLE_NAMES: Final[dict[AgentRole, tuple[str, str]]] = {
    role: (str(names[0]), str(names[1])) for role, names in _by_role("role_names").items()
}

_MISSIONS: Final[dict[AgentRole, str]] = {role: str(text) for role, text in _by_role("missions").items()}

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

# What each deliverable is called in the prose an agent writes. The ids stay the structured keys
# (release evidence, handoffs); the prompt names deliverables in Chinese so the plans read in Chinese.
ARTIFACT_LABELS: Final[dict[str, str]] = {
    artifact_id: str(label) for artifact_id, label in _table("artifact_labels").items()
}

def artifact_label(artifact_id: str) -> str:
    return ARTIFACT_LABELS.get(artifact_id, artifact_id)


_ROLE_GATES: Final[dict[AgentRole, tuple[str, ...]]] = {
    role: tuple(str(gate) for gate in gates) for role, gates in _by_role("role_gates").items()
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


# 能力目录的中文名与可执行策略按能力 id 存在措辞表里；id、负责角色、知识源、校验器与交付物是代码要比对的值，留在这里。
_CAPABILITY_WORDING: Final[dict[str, Any]] = _table("capabilities")


def _owned(
    capability_id: str,
    owners: tuple[AgentRole, ...],
    sources: tuple[str, ...],
    validator: str,
    artifacts: tuple[str, ...],
) -> CapabilityRecord:
    """A catalog entry whose label and policy are the wording table's ``capabilities.<capability_id>``."""
    wording = _CAPABILITY_WORDING[capability_id]
    return _cap(capability_id, str(wording["label"]), owners, sources, str(wording["policy"]), validator, artifacts)


_C = AgentRole
CAPABILITIES: Final[tuple[CapabilityRecord, ...]] = (
    _owned("genre_strategy", (_C.EXECUTIVE_DIRECTOR, _C.PR_AGENT),
           ("genre-summary", "production-guidelines", "industrial-production"),
           "validate_director_artifacts", ("genre_audience_strategy",)),
    _owned("golden_narrative", (_C.EXECUTIVE_DIRECTOR, _C.WRITER),
           ("golden-narrative", "production-guidelines", "cinema-craft-redlines", "episode-hook-ladder", "scene-craft-dialogue", "payoff-arc-craft",
            "character-relationship-craft", "causal-chain-craft", "tension-craft", "emotional-hook-craft"),
           "validate_narrative_contract", ("series_narrative_arc", "episode_scripts")),
    _owned("highlight_detection", (_C.EXECUTIVE_DIRECTOR, _C.PR_AGENT),
           ("highlight-detection",),
           "validate_highlight_map", ("highlight_map", "highlight_clips")),
    _owned("production_orchestration", (_C.EXECUTIVE_DIRECTOR,),
           ("industrial-production", "consistency-checklist"),
           "validate_council_coverage", ("director_constitution", "director_approval")),
    _owned("story_causality", (_C.WRITER, _C.EXECUTIVE_DIRECTOR),
           ("consistency-checklist", "golden-narrative", "cinema-craft-redlines", "episode-hook-ladder", "causal-chain-craft", "tension-craft",
            "xianxia-power-system", "xianxia-catalog", "xianxia-world"),
           "validate_narrative_contract", ("series_bible", "foreshadow_ledger")),
    _owned("dialogue_craft", (_C.WRITER, _C.AUDIO_DIRECTOR),
           ("dialogue-pacing", "production-guidelines", "cinema-craft-redlines", "scene-craft-dialogue", "poetry-recreation"),
           "validate_dialogue_contract", ("dialogue_sheet", "voice_cards")),
    _owned("dialogue_performance", (_C.AUDIO_DIRECTOR, _C.WRITER),
           ("dialogue-pacing", "performance-details"),
           "validate_audio_contract", ("dialogue_timing", "lipsync_plan")),
    _owned("five_view_identity", (_C.CHARACTER_DESIGNER,),
           ("actor-sheet-template", "consistency-checklist"),
           "validate_five_view_contract", ("five_view_turnarounds", "character_state_cards")),
    _owned("character_styling", (_C.CHARACTER_DESIGNER, _C.VISUAL_DIRECTOR),
           ("actor-sheet-template", "director-shot-guide"),
           "validate_character_artifacts", ("character_bible", "costume_makeup_ledger")),
    _owned("observable_acting", (_C.CHARACTER_DESIGNER, _C.STORYBOARD_ARTIST, _C.VISUAL_DIRECTOR),
           ("performance-details", "emotion-expression", "martial-arts"),
           "validate_performance_contract", ("character_bible", "shot_motion_contracts", "visual_qc")),
    _owned("scene_bible", (_C.STORYBOARD_ARTIST, _C.VISUAL_DIRECTOR),
           ("scene-design", "continuity-design"),
           "validate_scene_contract", ("scene_bibles", "visual_bible")),
    _owned("shot_grammar", (_C.STORYBOARD_ARTIST,),
           ("director-shot-guide", "visual-style", "high-tension-shots"),
           "validate_storyboard_contract", ("shot_motion_contracts",)),
    _owned("blocking_axis", (_C.STORYBOARD_ARTIST, _C.VISUAL_DIRECTOR),
           ("director-shot-guide", "continuity-design", "shot-group-and-handoff-checks"),
           "validate_continuity_contract", ("continuity_ledger", "reference_binding_plan")),
    _owned("exact_nine_grid", (_C.STORYBOARD_ARTIST,),
           ("actor-sheet-template", "plot-shot-coherence"),
           "validate_nine_grid_contract", ("exact_nine_grid_storyboards", "storyboard_qc")),
    _owned("continuity_six_anchors", (_C.STORYBOARD_ARTIST, _C.VISUAL_DIRECTOR, _C.COMPOSER_PUBLISHER),
           ("plot-shot-coherence", "continuity-design", "consistency-checklist", "frame-handoff-action-light-tone", "shot-group-and-handoff-checks", "cut-connection-ideas", "segment-relay-and-fight-keyframes"),
           "validate_continuity_contract", ("continuity_ledger", "transition_plan")),
    _owned("fight_choreography", (_C.STORYBOARD_ARTIST, _C.VISUAL_DIRECTOR, _C.AUDIO_DIRECTOR),
           ("martial-arts", "segment-relay-and-fight-keyframes"),
           "validate_action_contract", ("action_choreography", "sfx_foley_cues")),
    _owned("visual_style", (_C.VISUAL_DIRECTOR, _C.EXECUTIVE_DIRECTOR),
           ("visual-style", "director-shot-guide"),
           "validate_visual_contract", ("style_palette_lighting_lock",)),
    # 编剧之后的六个角色共同持有：出图出视频的角色负责编译执行，
    # 音频/合成/宣发角色负责按同一模块清单做核验与归档，口径不分叉。
    _owned("negative_prompt_router", POST_WRITER_ROLES,
           ("negative-prompts", "emotion-expression"),
           "validate_visual_contract", ("negative_prompt_plan",)),
    _owned("reference_generation", (_C.VISUAL_DIRECTOR, _C.STORYBOARD_ARTIST),
           ("actor-sheet-template", "continuity-design", "industrial-production"),
           "validate_video_route_contract", ("video_route_plans", "reference_binding_plan")),
    _owned("prompt_fingerprint", (_C.STORYBOARD_ARTIST, _C.VISUAL_DIRECTOR),
           ("actor-sheet-template",),
           "validate_fingerprint_contract", ("shot_motion_contracts", "generated_keyframes")),
    _owned("visual_quality_repair", (_C.VISUAL_DIRECTOR, _C.COMPOSER_PUBLISHER),
           ("consistency-checklist", "performance-details", "production-guidelines"),
           "validate_visual_contract", ("visual_qc", "final_qc")),
    _owned("elevenlabs_audio", (_C.AUDIO_DIRECTOR,),
           ("dialogue-pacing", "production-guidelines", "industrial-production"),
           "validate_audio_contract", ("elevenlabs_job_plan",)),
    _owned("voice_identity", (_C.AUDIO_DIRECTOR, _C.CHARACTER_DESIGNER),
           ("dialogue-pacing", "performance-details"),
           "validate_audio_contract", ("voice_cards", "voice_identity_brief")),
    _owned("sfx_bgm_mix", (_C.AUDIO_DIRECTOR, _C.COMPOSER_PUBLISHER),
           ("production-guidelines", "martial-arts", "continuity-design"),
           "validate_audio_contract", ("sfx_foley_cues", "bgm_music_plan", "audio_mix_plan")),
    _owned("lip_sync", (_C.AUDIO_DIRECTOR, _C.COMPOSER_PUBLISHER),
           ("performance-details", "dialogue-pacing"),
           "validate_lipsync_contract", ("lipsync_plan", "subtitle_package")),
    _owned("editing_transitions", (_C.COMPOSER_PUBLISHER, _C.STORYBOARD_ARTIST),
           ("continuity-design", "production-guidelines", "director-shot-guide", "frame-handoff-action-light-tone"),
           "validate_delivery_contract", ("edit_decision_list", "transition_plan")),
    _owned("delivery_master", (_C.COMPOSER_PUBLISHER,),
           ("production-guidelines", "visual-style", "consistency-checklist"),
           "validate_delivery_contract", ("mastered_timeline", "export_profiles", "delivery_archive")),
    _owned("release_gate", (_C.EXECUTIVE_DIRECTOR, _C.COMPOSER_PUBLISHER),
           ("consistency-checklist",),
           "evaluate_release", ("final_qc", "director_approval")),
    _owned("marketing_package", (_C.PR_AGENT,),
           ("highlight-detection", "production-guidelines", "industrial-production"),
           "validate_marketing_contract", ("cover_title_variants", "trailer_plan", "platform_copy_tags")),
    _owned("growth_loop", (_C.PR_AGENT, _C.EXECUTIVE_DIRECTOR),
           ("production-guidelines", "genre-summary"),
           "validate_marketing_contract", ("ab_test_plan", "campaign_kpis")),
    _owned("rights_provenance", (_C.PR_AGENT, _C.COMPOSER_PUBLISHER, _C.EXECUTIVE_DIRECTOR),
           ("production-guidelines", "consistency-checklist"),
           "validate_provenance_contract", ("rights_ai_disclosure", "delivery_archive", "production_risk_register")),
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
            subtitle_safe_zone=_says("delivery.subtitle_safe_zone_landscape"),
        )
    return DeliveryProfile(
        aspect_ratio="9:16", width=1080, height=1920, fps=30,
        subtitle_safe_zone=_says("delivery.subtitle_safe_zone_portrait"),
    )


# 负面词模块词表：id 对照负面提示词指南（negative-prompts 章节）的章节，
# negative_prompt_router 的可执行策略(通用/脸/手/多人/服装/场景/材质/时序/表演/题材)逐项落到这里。
NEGATIVE_MODULE_LABELS: Final[dict[str, str]] = {
    module: str(label) for module, label in _table("negative.module_labels").items()
}

# 模块 → 可直接拼进生成提示词的负面词串。词条从负面提示词指南（negative-prompts 章节）对应章节精选，
# 每模块只保留压制力最强的少数词(知识源 §17.3 关键压制项优先级)；多模块叠加后仍要能
# 活过 Agnes 网关的截断预算——绝不整章搬运(知识源使用原则 1「不要一次性把负面词堆满」)。
# 只禁叠加上去的东西：text_watermark 裸写 text 会让模型去擦场景里原有的匾额、对联、招牌。短一点，预算内才轮得到它。
NEGATIVE_MODULE_WORDS: Final[dict[str, str]] = {
    module: str(words) for module, words in _table("negative.module_words").items()
}


def compile_negative_prompt(modules: list[str], *, budget: int = 420) -> str:
    """把角色配药单编译成可拼进生成提示词的负面词串，形如 ``(避免：a, b, c)``。

    词条按模块顺序展开并跨模块去重；超出预算时按整模块丢弃(不截半个词条)，
    宁可少压一个模块也不给模型半句负面词。空配药单返回空串，调用方零成本拼接。
    括号包裹与既有 SHEET_LOCK_NEGATIVE 等常量同构，Agnes 网关的负面块清洗按同一规则处理。
    """
    seen: set[str] = set()
    words: list[str] = []
    length = 0
    for module in modules:
        chunk = NEGATIVE_MODULE_WORDS.get(module, "")
        if not chunk:
            continue
        fresh = [w.strip() for w in chunk.split(",") if w.strip() and w.strip() not in seen]
        if not fresh:
            continue
        added = sum(len(w) + 2 for w in fresh)
        if length + added > budget:
            continue
        seen.update(fresh)
        words.extend(fresh)
        length += added
    if not words:
        return ""
    return _says("negative.prompt", words=", ".join(words))


_NEGATIVE_BASE_MODULES: Final[tuple[str, ...]] = tuple(str(module) for module in _table("negative.base_modules"))

# 每个下游角色按自己真正调用的生成接口筛模块，不是复制全量词表。
# 依据：知识源 §17.2「不同任务的推荐组合」与各角色在流水线里的实际产出形态。
# 数字演员设定集是静态设定图、全片身份锚点：压五官漂移/手部崩塌/服装走样/配色不稳，不发时序词。
# 九宫格同样是静图，但要处理群像、机位与场景圣经，仍不发时序词。
# 视觉总监是唯一同时出图与出视频的角色，时序连续性必发；机位由上游 ShotMotionContract 锁定，本阶段不再重复压制镜头语言。
# TTS/音乐/音效接口只接受一个正向字符串，没有负面词通道：音频总监只保留与口型时序、念白表演真正相关的两项，作为核验口径而非画面约束。
# 合成发布不调用任何生成模型：它的三项是在母版与转场上的核验与归档口径。
# 宣发当前不产出画面，只在封面与物料描述上沿用同一身份与错字水印边界。
_ROLE_NEGATIVE_MODULES: Final[dict[AgentRole, tuple[str, ...]]] = {
    role: tuple(str(module) for module in modules) for role, modules in _by_role("negative.role_modules").items()
}

# 题材与高动作追加项只发给真正能对画面动手的角色。
_ROLE_GENRE_NEGATIVE_MODULES: Final[dict[str, tuple[AgentRole, ...]]] = {
    module: tuple(AgentRole(role) for role in roles) for module, roles in _table("negative.genre_roles").items()
}

# 题材触发词：按顺序逐条比对小写后的题材，包含任一词即追加该模块；高动作强度再追加一组。
_GENRE_NEGATIVE_TRIGGERS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = tuple(
    (str(module), tuple(str(word) for word in words)) for module, words in _table("negative.genre_triggers")
)
_HIGH_ACTION_NEGATIVE_MODULES: Final[tuple[str, ...]] = tuple(
    str(module) for module in _table("negative.high_action_modules")
)


def _negative_modules(request: CouncilCompileRequest) -> list[str]:
    """全局词表：本次项目允许使用的负面词模块全集(扁平清单，兼容既有调用方)。"""
    modules = list(_NEGATIVE_BASE_MODULES)
    genre = request.genre.lower()
    for module, triggers in _GENRE_NEGATIVE_TRIGGERS:
        if any(word in genre for word in triggers):
            modules.append(module)
    if request.action_intensity == "high":
        modules.extend(_HIGH_ACTION_NEGATIVE_MODULES)
    return modules


def _negative_modules_by_role(catalog: list[str]) -> dict[AgentRole, list[str]]:
    """把全局词表按角色职责筛成配药单，编剧之后的六个角色各一份。"""
    available = set(catalog)
    by_role: dict[AgentRole, list[str]] = {}
    for role in POST_WRITER_ROLES:
        selected = [module for module in _ROLE_NEGATIVE_MODULES[role] if module in available]
        selected.extend(
            module for module in catalog
            if module in _ROLE_GENRE_NEGATIVE_MODULES
            and role in _ROLE_GENRE_NEGATIVE_MODULES[module]
            and module not in selected
        )
        by_role[role] = selected
    return by_role


def _source_records() -> list[KnowledgeSourceRecord]:
    keys = knowledge_source_keys()
    capability_ids_by_source: dict[str, list[str]] = {key: [] for key in keys}
    for capability in CAPABILITIES:
        for key in capability.source_files:
            if key not in capability_ids_by_source:
                raise RuntimeError(f"unknown knowledge section in capability catalog: {key}")
            capability_ids_by_source[key].append(capability.id)

    records: list[KnowledgeSourceRecord] = []
    for key in keys:
        section = knowledge_registry.section(key)
        if section is None or not section.path.is_file():
            raise RuntimeError(f"required production knowledge section is missing: {key}")
        data = section.path.read_bytes()
        records.append(KnowledgeSourceRecord(
            filename=key,
            project_relative_path=f"skills/{section.relative_path}",
            sha256=hashlib.sha256(data).hexdigest(),
            byte_size=len(data),
            capability_ids=sorted(capability_ids_by_source[key]),
        ))
    return records


def _role_capabilities(role: AgentRole) -> list[CapabilityRecord]:
    return [capability for capability in CAPABILITIES if role in capability.owners]


def _role_prompt(
    role: AgentRole,
    request: CouncilCompileRequest,
    delivery: DeliveryProfile,
    constitution: ProductionConstitution,
    negative_modules: list[str] | None = None,
) -> str:
    name_zh, name_en = _ROLE_NAMES[role]
    capabilities = _role_capabilities(role)
    policies = "\n".join(
        _says("role_prompt.policy_line", capability_id=item.id, policy=item.executable_policy) for item in capabilities
    )
    outputs = _table("role_prompt.output_separator").join(artifact_label(item) for item in _ROLE_OUTPUTS[role])
    gates = "\n".join(_says("role_prompt.gate_line", gate=gate) for gate in _ROLE_GATES[role])
    # 只有编剧之后的角色带负面词小节；总导演与编剧的提示词保持原样。
    negative_section = ""
    if negative_modules:
        rendered = "\n".join(
            _says("role_prompt.negative_module_line", module=module, label=NEGATIVE_MODULE_LABELS.get(module, module))
            for module in negative_modules
        )
        negative_section = _says(
            "role_prompt.negative_section",
            source_title=knowledge_registry.section_title("negative-prompts"),
            modules=rendered,
        )
    return _says(
        "role_prompt.body",
        name_zh=name_zh,
        name_en=name_en,
        title=request.title,
        genre=request.genre,
        audience=request.audience,
        platform=request.platform,
        format=request.format,
        language=request.output_language,
        mission=_MISSIONS[role],
        width=delivery.width,
        height=delivery.height,
        aspect_ratio=delivery.aspect_ratio,
        fps=delivery.fps,
        hook_seconds=constitution.opening_hook_deadline_seconds,
        dialogue_max=constitution.dialogue_max_han_characters,
        release_threshold=constitution.release_threshold,
        policies=policies,
        outputs=outputs,
        negative_section=negative_section,
        gates=gates,
    )


def _handoffs() -> list[AgentHandoff]:
    pairs = list(zip(ALL_AGENT_ROLES, ALL_AGENT_ROLES[1:]))
    handoffs = [
        AgentHandoff(
            producer=producer,
            consumer=consumer,
            required_artifacts=list(_ROLE_OUTPUTS[producer]),
            acceptance_rules=[str(rule) for rule in _table("handoff.rules")],
        )
        for producer, consumer in pairs
    ]
    handoffs.append(AgentHandoff(
        producer=AgentRole.PR_AGENT,
        consumer=AgentRole.EXECUTIVE_DIRECTOR,
        required_artifacts=["rights_ai_disclosure", "campaign_kpis", "highlight_clips"],
        acceptance_rules=[str(rule) for rule in _table("handoff.closing_rules")],
    ))
    return handoffs


# 发布门禁的阈值：未解决B级问题上限、核心维度均分下限(满分5)、总分下限(满分100)。
_UNRESOLVED_B_LIMIT: Final = 3
_CORE_AVERAGE_MINIMUM: Final = 4.0
_TOTAL_SCORE_MINIMUM: Final = 85


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
        # 先算全局词表，再按角色筛配药单，"分档 ⊆ 全局"在构造时天然成立。
        negative_catalog = _negative_modules(request)
        negative_by_role = _negative_modules_by_role(negative_catalog)
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
                system_prompt=_role_prompt(
                    role, request, delivery, constitution, negative_by_role.get(role),
                ),
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
            negative_prompt_modules=negative_catalog,
            negative_prompt_by_role=negative_by_role,
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
            detail=(
                _says("release.roles_unique") if not duplicate_roles
                else _says("release.roles_duplicated", roles=sorted(role.value for role in duplicate_roles))
            ),
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
                detail=(
                    _says("release.artifacts_complete") if present
                    else _says("release.artifacts_missing", missing=missing or [_table("release.whole_stage_evidence")])
                ),
                owner=role,
            ))
            approved = approvals.get(role, False)
            checks.append(ReleaseCheck(
                code=f"agent.{role.value}.approved",
                passed=approved,
                detail=_says("release.stage_approved") if approved else _says("release.stage_unapproved"),
                owner=role,
            ))

        # 当前契约的五个身份锚点，或旧五视图顺序（存量项目的证据包还是老键）。
        identity_order_ok = identity_view_order_is_valid(tuple(evidence.five_view_order))
        nine_grid_ok = (
            evidence.storyboard_rows == 3 and evidence.storyboard_columns == 3 and 1 <= evidence.storyboard_panel_count <= 9
        )
        video_route_ok = evidence.video_route_accepted and not evidence.unsupported_references_dropped
        structural = (
            ("character.five_view_order", identity_order_ok,
             _says("release.five_view_order_ok") if identity_order_ok else _says("release.five_view_order_bad"),
             AgentRole.CHARACTER_DESIGNER),
            ("storyboard.exact_nine_grid", nine_grid_ok,
             _says("release.nine_grid", rows=evidence.storyboard_rows, columns=evidence.storyboard_columns,
                   panels=evidence.storyboard_panel_count),
             AgentRole.STORYBOARD_ARTIST),
            ("storyboard.motion_fingerprint", evidence.storyboard_motion_fingerprints_match,
             _says("release.motion_fingerprint_ok") if evidence.storyboard_motion_fingerprints_match
             else _says("release.motion_fingerprint_bad"),
             AgentRole.VISUAL_DIRECTOR),
            ("video.route_accepted", video_route_ok,
             _says("release.video_route_ok") if video_route_ok else _says("release.video_route_bad"),
             AgentRole.VISUAL_DIRECTOR),
            ("audio.dialogue_timing", evidence.dialogue_timing_approved,
             _says("release.dialogue_timing_ok") if evidence.dialogue_timing_approved else _says("release.dialogue_timing_bad"),
             AgentRole.AUDIO_DIRECTOR),
            ("audio.mix", evidence.audio_mix_approved,
             _says("release.audio_mix_ok") if evidence.audio_mix_approved else _says("release.audio_mix_bad"),
             AgentRole.AUDIO_DIRECTOR),
            ("delivery.final_media", evidence.final_media_present,
             _says("release.final_media_ok") if evidence.final_media_present else _says("release.final_media_bad"),
             AgentRole.COMPOSER_PUBLISHER),
            ("delivery.subtitles", evidence.subtitles_approved,
             _says("release.subtitles_ok") if evidence.subtitles_approved else _says("release.subtitles_bad"),
             AgentRole.COMPOSER_PUBLISHER),
            ("compliance.rights_provenance", evidence.rights_and_provenance_approved,
             _says("release.rights_provenance_ok") if evidence.rights_and_provenance_approved
             else _says("release.rights_provenance_bad"),
             AgentRole.PR_AGENT),
            ("compliance.platform", evidence.platform_compliance_approved,
             _says("release.platform_ok") if evidence.platform_compliance_approved else _says("release.platform_bad"),
             AgentRole.PR_AGENT),
            ("review.human_final", evidence.human_final_review,
             _says("release.human_final_ok") if evidence.human_final_review else _says("release.human_final_bad"),
             AgentRole.EXECUTIVE_DIRECTOR),
        )
        checks.extend(ReleaseCheck(code=code, passed=passed, detail=detail, owner=owner) for code, passed, detail, owner in structural)

        unresolved = [issue for issue in evidence.issues if not issue.resolved]
        severity_counts = {severity: sum(issue.severity == severity for issue in unresolved) for severity in ("S", "A", "B", "C")}
        severity_rules = (
            ("issues.no_unresolved_s", severity_counts["S"] == 0, _says("release.none_unresolved", severity="S")),
            ("issues.no_unresolved_a", severity_counts["A"] == 0, _says("release.none_unresolved", severity="A")),
            ("issues.b_within_limit", severity_counts["B"] <= _UNRESOLVED_B_LIMIT,
             _says("release.b_within_limit", count=severity_counts["B"], limit=_UNRESOLVED_B_LIMIT)),
        )
        checks.extend(ReleaseCheck(code=code, passed=passed, detail=detail, owner=AgentRole.EXECUTIVE_DIRECTOR) for code, passed, detail in severity_rules)

        core_scores = [evidence.dimension_scores[name] for name in CORE_SCORE_DIMENSIONS]
        core_average = round(sum(core_scores) / len(core_scores), 4)
        total_score = round(core_average / 5 * 100, 2)
        checks.extend([
            ReleaseCheck(
                code="score.core_average", passed=core_average >= _CORE_AVERAGE_MINIMUM,
                detail=_says("release.core_average", average=core_average, minimum=_CORE_AVERAGE_MINIMUM),
                owner=AgentRole.EXECUTIVE_DIRECTOR,
            ),
            ReleaseCheck(
                code="score.total", passed=total_score >= _TOTAL_SCORE_MINIMUM,
                detail=_says("release.total_score", total=total_score, minimum=_TOTAL_SCORE_MINIMUM),
                owner=AgentRole.EXECUTIVE_DIRECTOR,
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
                summary[issue.owner.value].append(
                    _says("release.issue_line", severity=issue.severity, code=issue.code, detail=issue.detail)
                )
        return {role: records for role, records in summary.items() if records}
