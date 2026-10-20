"""Auditable upstream capability map. No third-party code is executed here."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import TypedDict

from app.core.provenance import upstream_source_by_id


class CapabilitySource(TypedDict):
    id: str
    source: str
    capabilities: list[str]


UPSTREAM_CAPABILITIES: list[CapabilitySource] = [
    {
        "id": "minimax-h3-skills",
        "source": "https://github.com/MiniMax-AI/MiniMax-H3/tree/main/skills",
        "capabilities": [
            "H3 prompt compiler", "text/first/last/first-last frame video", "multi-reference video",
            "3D animation short", "brand promo", "co-op game intro", "hand-drawn live action",
            "minimalist product ad", "music-video subtitles", "paper collage", "papercraft stop motion",
        ],
    },
    {
        "id": "drama-skills",
        "source": "https://github.com/worldwonderer/drama-skills.git",
        "capabilities": [
            "script analysis", "long-novel adaptation triage", "resumable multi-episode intake",
            "reference-backed voice direction", "output and prompt language contract",
            "character bible", "storyboard", "prompt generation", "continuity QA",
        ],
    },
    {
        "id": "facial-expression-prompting",
        "source": "https://github.com/zhouwei713/facial-expression-prompting.git",
        "capabilities": ["facial action cues", "micro-expression prompting", "emotion progression", "performance QA"],
    },
    {
        "id": "visual-skills",
        "source": "https://github.com/smixs/visual-skills.git",
        "capabilities": ["cinematography vocabulary", "composition", "lighting", "visual continuity", "visual QA"],
    },
    {
        "id": "dramaclaw",
        "source": "https://github.com/dramaclaw/dramaclaw.git",
        "capabilities": [
            "agent workflow", "project orchestration", "asset management", "provider integration",
            "dual-track Freezone canvas outline and duplication",
        ],
    },
    {
        "id": "instant-video",
        "source": "https://github.com/briefness/InstantVideo.git",
        "capabilities": [
            "rapid video generation", "task workflow", "production readiness",
            "structured failure evidence", "production analytics", "media assembly", "export",
        ],
    },
    {
        "id": "video-shotcraft",
        "source": "https://github.com/Vincentwei1021/video-shotcraft.git",
        "capabilities": [
            "shot grammar", "camera movement", "storyboard planning", "video prompt craft",
            "Jianying editable draft export",
        ],
    },
    {
        "id": "fast-movie-ai",
        "source": "https://gitee.com/yc_open/FastMovieAI.git",
        "capabilities": ["script-to-movie pipeline", "character/scene assets", "voice", "video composition", "project UI"],
    },
    {
        "id": "arcreel",
        "source": "https://github.com/ArcReel/ArcReel.git",
        "capabilities": [
            "story graph", "shot generation", "asset/reference management", "render workflow", "timeline",
            "episode ledger planning", "two-stage script authoring", "verbatim utterance capture",
            "model-bound shot duration contract", "incremental plan editing", "prompt audit preview",
            "shot camera-motion workspace",
            "whole-source and own-source episode library", "batch video admission",
            "provider call usage ledger", "speech ownership and narration delivery", "subtitle draft",
            "asset name identity with rename cascade and merge aliases",
            "provider video job checkpoint, restart resume and clip reuse",
            "per-shot regeneration with reuse of the rest", "self-hosted OpenAI-compatible provider",
            "episode ledger operations: manual split/merge/cut, create/move/delete with impact preview, candidate replan compare-and-adopt",
            "fingerprint-bound episode review with a soft production gate, violating-draft quarantine and non-degrading AI repair",
            "persistent generation queue with per provider-family x medium ceilings, item dependencies and cancel-only-queued",
            "credential pools per provider with job-type buckets and refusal cooldown",
            "video providers declared in data (submit / poll / result paths)", "self-hosted ComfyUI workflow provider (workflow required)",
            "edit timeline with trims, transitions, subtitles, per-clip review and local re-render", "music library with uploads and generated beds",
            "JianYing draft export (draft_content / draft_meta_info with packed media)",
            "per-clip material review: approve or send back before the final cut",
            "one tool catalog for agents with read / write / paid effects and ownership checks", "embedded tool assistant in project chat (/agent, /confirm)",
            "remote MCP server (JSON-RPC over POST /mcp) exposing the same tools", "per-user MCP bearer tokens issued in the user centre",
            "creation types: drama / narration / ad with their own plan rules and episode frame", "ad brief (product, selling points, audience, call to action)",
            "character derived looks bound by trigger words or episode range", "product assets bound by mention and required for an ad's brief",
            "style lock read off a reference image by a vision model",
            "interface in zh / en / vi with Chinese fallback and a coverage check", "script content language per project (zh / en / vi) applied to every writing prompt",
            "market sources as repositories (index + definitions over raw file addresses, no central service)", "market installs as a separate record: editable in place, version-equality updates, unavailable when delisted",
        ],
    },
    {
        "id": "script-to-shot-engine",
        "source": "https://github.com/jiayushi1-ux/script-to-shot-engine.git",
        "capabilities": ["script parsing", "shot decomposition", "structured shot output", "duration and camera planning"],
    },
    {
        "id": "script-to-video-prompts",
        "source": "https://github.com/Morris1029/script-to-video-prompts.git",
        "capabilities": [
            "TXT/Markdown/DOCX/PDF/FDX ingestion",
            "script element parsing",
            "character/costume/five-view profiles",
            "scene/light/color analysis",
            "exact nine-grid shot prompts",
            "character/scene/lighting/prop/effect consistency checks",
            "SD25 prompt optimization",
            "automatic first-last/multi-image/multimodal video routing",
            "JSON/Markdown/CSV/XLSX/HTML export",
        ],
    },
    {
        "id": "video-agent-skills",
        "source": "https://github.com/towardsyoung/video-agent-skills",
        "capabilities": ["video-agent skill routing", "pre-production", "generation", "editing", "quality control"],
    },
    {
        "id": "short-drama-skills",
        "source": "https://github.com/YvonneMovingon/short-drama-skills.git",
        "capabilities": [
            "narrative breakdown", "power-shift emotional dialogue", "detailed action", "episode continuity grouping",
            "single-video prompt polish", "high-impact drama", "slow cinematic emotion",
        ],
    },
    {
        "id": "sd-2-5-prompt",
        "source": "https://github.com/huangbai-AI/sd-2-5-prompt",
        "capabilities": [
            "five-part Seedance prompt organization",
            "continuous timeline audit",
            "reference responsibility audit",
            "complex-action causality audit",
            "unbranded prompt boundary audit",
        ],
    },
    {
        "id": "fight-prompt-director",
        "source": "https://github.com/irenerachel/fight-prompt-director",
        "capabilities": [
            "fight scene detection",
            "fight-specific skill section loading",
            "standard and express speed tiers",
            "three intensity plans",
            "quantified fight beats",
            "fight negative-prompt and anti-collapse contract",
            "vendored fight director skill discovery",
        ],
    },
    {
        "id": "fight-video-create-skill",
        "source": "https://github.com/qualsenWeb/fight-video-create-skill",
        "capabilities": [
            "fight design rules in the episode plan",
            "one exchange per fight shot in the visual layer",
            "shared fight detection for writer and storyboard",
        ],
    },
    {
        "id": "seedance-2-5-video-director",
        "source": "https://github.com/liyue-aigc/seedance-2-5-video-director",
        "capabilities": [
            "seedance 2.5 model gate",
            "seedance primary mode selection",
            "seedance mode limits and input requirements",
            "seedance asset lock and person reference scope",
            "seedance realistic performance and physical causality",
            "seedance director layer in video prompt optimizer",
        ],
    },
    {
        "id": "storyai-3d-director-desk",
        "source": "https://github.com/jiguang132/storyai-3d-director-desk",
        "capabilities": [
            "per-scene stage of characters, set pieces and look-at cameras",
            "director view and camera view of one stage",
            "delivery-aspect camera frame",
            "pose preset vocabulary for stand-in figures",
            "per-scene stage scoping inside a host workbench",
            "director desk project JSON interchange",
        ],
    },
    {
        "id": "director-desk",
        "source": "https://github.com/mangfufu/director-desk",
        "capabilities": [
            "camera move presets written as editable timeline keys",
            "film-back framing from shot size",
            "deterministic frame-by-frame blockout clip export",
            "hand-drawn walk and camera routes resampled into keys",
            "depth stills and depth video as generation references",
            "set-piece arrays and alignment for fast set building",
        ],
    },
    {
        "id": "costage",
        "source": "https://github.com/cs68614-hash/costage",
        "capabilities": [
            "camera-relative and character-relative placement",
            "facing pair blocking",
            "line / arc / circle / grid formations with facing",
            "field-of-view framing from shot size",
            "action stage must change character state",
            "revision-pinned semantic stage operations",
            "CoStage document interchange",
        ],
    },
]


MANDATORY_PIPELINE_GATES = [
    "eight-agent artifact completeness and S/A/B/C release gate",
    "story asset catalog: characters/scenes/props/effects",
    "ordered five-view character turnaround",
    "exact 3x3 nine-grid storyboard",
    "multi-image/multimodal/first-last-frame generation",
    "character/expression/photorealism/continuity acceptance gates",
    "natural visual and audio transitions",
    "ElevenLabs TTS/dialogue/SFX/music/STT/dubbing",
    "MiniMax H3 video generation",
    "sd25-pe prompt compiler",
]


# Entry points are positionally aligned with each source's capability list. A
# startup assertion below prevents unrelated labels from sharing evidence by
# modulo/round-robin fallback.
_IMPLEMENTATION_ENTRYPOINTS: dict[str, list[str]] = {
    "minimax-h3-skills": [
        "/api/production/video/minimax-h3", "/api/production/video/minimax-h3",
        "/api/production/video/minimax-h3", "/api/production/presets/{preset_id}/compile",
        "/api/production/presets/{preset_id}/compile", "/api/production/presets/{preset_id}/compile",
        "/api/production/presets/{preset_id}/compile", "/api/production/presets/{preset_id}/compile",
        "/api/production/presets/{preset_id}/compile", "/api/production/presets/{preset_id}/compile",
        "/api/production/presets/{preset_id}/compile",
    ],
    "drama-skills": [
        "/api/production/preproduction/novel-analyze", "/api/production/preproduction/novel-analyze",
        "/api/production/preproduction/episodes/index", "/api/production/preproduction/voice/plan",
        "/api/production/preproduction/novel-analyze", "app.service.drama_service.DramaService",
        "/api/production/storyboards/compile", "/api/production/sd25/compile",
        "/api/production/quality/video/decision",
    ],
    "facial-expression-prompting": [
        "/api/production/performance/plan", "/api/production/performance/plan",
        "/api/production/performance/plan", "/api/production/quality/video/decision",
    ],
    "visual-skills": [
        "/api/production/storyboards/compile", "/api/production/storyboards/compile",
        "/api/production/storyboards/compile", "app.core.continuity.plan_transition",
        "/api/production/quality/video/decision",
    ],
    "dramaclaw": [
        "/api/studio/projects", "/api/studio/projects", "/api/studio/projects/{project_id}/artifacts",
        "/api/production/providers", "/api/studio/projects/{project_id}/canvas/outline",
    ],
    "instant-video": [
        "app.service.drama_service.DramaService", "/api/studio/projects/{project_id}/jobs",
        "/api/production/readiness/evaluate", "/api/production/failures/normalize",
        "/api/production/analytics/summarize", "app.core.media_compositor.compose_film",
        "/api/studio/exports/preview",
    ],
    "video-shotcraft": [
        "/api/production/shotcraft/catalog", "/api/production/shotcraft/compile",
        "/api/production/storyboards/compile", "/api/production/shotcraft/compile",
        "/api/studio/exports/preview",
    ],
    "fast-movie-ai": [
        "app.service.drama_service.DramaService", "app.service.drama_service.DramaService",
        "/api/production/audio/tts", "app.core.media_compositor.compose_film",
        "/api/studio/projects",
    ],
    "arcreel": [
        "/api/studio/projects/{project_id}/canvas", "/api/production/video/minimax-h3",
        "/api/studio/projects/{project_id}/artifacts", "/api/studio/projects/{project_id}/jobs",
        "/api/studio/exports/preview",
        "/api/drama/{task_id}/screenwriting", "app.core.screenwriting.engine.ScreenwritingEngine",
        "app.core.screenwriting.models.Utterance", "app.core.screenwriting.durations.supported_shot_durations",
        "/api/drama/{task_id}/screenwriting/episodes/{episode}/plan",
        "/api/drama/{task_id}/screenwriting/episodes/{episode}/prompt",
        "/api/drama/{task_id}/shots/{shot_id}/visual",
        "/api/drama/{task_id}/script-documents", "/api/drama/{task_id}/shots/admission",
        "/api/drama/{task_id}/usage", "app.core.screenwriting.speech.speech_mode",
        "/api/drama/{task_id}/subtitles", "/api/drama/{task_id}/assets/rename",
        "app.core.video_jobs.resume_outcome", "/api/drama/{task_id}/shots/{shot_id}/regenerate",
        "app.core.model_configuration.CUSTOM_PROVIDERS",
        "/api/drama/{task_id}/screenwriting/ledger/ops",
        "/api/drama/{task_id}/screenwriting/episodes/{episode}/review",
        "/api/drama/{task_id}/queue",
        "/api/model-configurations/{configuration_id}/credentials",
        "/api/model-configurations/settings/video-endpoints/{family}", "app.core.providers.comfyui.status",
        "/api/drama/{task_id}/timeline", "/api/library/bgm", "/api/drama/{task_id}/timeline/jianying.zip",
        "/api/drama/{task_id}/timeline/ops",
        "app.core.agent_tools.catalog", "/api/drama/{task_id}/assistant", "/mcp", "/api/mcp/tokens",
        "app.core.creation_modes.writer_guidance", "app.core.creation_modes.ad_brief",
        "/api/elements/{element_id}/variant", "app.core.storyboard_scene_context.panel_context",
        "/api/drama/{task_id}/style/reference",
        "frontend/src/i18n/index.ts", "app.core.screenwriting.prompts.language_scope",
        "/api/market/sources", "/api/market/sources/{source_id}/entries/{slug}/install",
    ],
    "script-to-shot-engine": [
        "/api/production/storyboards/compile", "/api/production/storyboards/compile",
        "/api/production/storyboards/compile", "/api/production/storyboards/compile",
    ],
    "script-to-video-prompts": [
        "/api/production/script-prompts/compile-file", "/api/production/script-prompts/compile",
        "/api/production/script-prompts/compile", "/api/production/script-prompts/compile",
        "/api/production/script-prompts/compile", "/api/production/script-prompts/compile",
        "/api/production/sd25/compile", "/api/production/script-prompts/compile",
        "/api/production/script-prompts/compile",
    ],
    "video-agent-skills": [
        "/api/production/providers", "/api/production/preproduction/novel-analyze",
        "/api/production/video/minimax-h3", "app.core.media_compositor.compose_film",
        "/api/production/quality/video/decision",
    ],
    "short-drama-skills": [
        "/api/production/preproduction/episodes/index", "/api/production/performance/plan",
        "/api/production/performance/plan", "app.core.continuity.plan_transition",
        "/api/production/presets/{preset_id}/compile", "/api/production/presets/{preset_id}/compile",
        "/api/production/presets/{preset_id}/compile",
    ],
    "sd-2-5-prompt": [
        "app.core.model_gateway.ModelGateway.optimize_video_prompt",
        "/api/production/sd25/audit", "/api/production/sd25/audit",
        "/api/production/sd25/audit", "/api/production/sd25/audit",
    ],
    # 打戏能力全部落在阶段四的分镜提示词上：先判场次类型，再按类型换章节与预算，
    # 速度档位/强度方案/量化节拍/负面词串都是被装载进去的正文，不是另起的接口。
    "fight-prompt-director": [
        "app.service.drama_service.DramaService._detect_scene_kind",
        "app.core.shot_design_skill.section_budgets",
        "app.service.drama_service.DramaService.storyboard_skill_prefix",
        "app.service.drama_service.DramaService.storyboard_skill_prefix",
        "app.service.drama_service.DramaService.storyboard_skill_prefix",
        "app.service.drama_service.DramaService.storyboard_skill_prefix",
        "/api/drama/skills",
    ],
    # 打戏设计前移到编剧阶段：本集含打戏时，分集规划与视觉层各带一段打戏规则；
    # 判定词表与阶段四共用 app.core.fight_design。
    "fight-video-create-skill": [
        "app.core.screenwriting.prompts.build_script_plan_prompt",
        "app.core.screenwriting.prompts.build_visual_prompt",
        "app.core.fight_design.looks_like_fight",
    ],
    # Seedance 2.5 导演层：先判模型版本，再选主模式，然后把上限/素材/表演章节按预算
    # 打包，最后作为第三段系统提示追加进视频提示词优化器。2.0 与其它模型不套用。
    "seedance-2-5-video-director": [
        "app.core.seedance_video_director.is_seedance_25",
        "app.core.seedance_video_director.select_primary_mode",
        "app.core.seedance_video_director.build_director_layer",
        "app.core.seedance_video_director.build_director_layer",
        "app.core.seedance_video_director.build_director_layer",
        "app.core.model_gateway.ModelGateway.optimize_video_prompt",
    ],
    "storyai-3d-director-desk": [
        "app.core.spatial_stage.models.StagePlan",
        "frontend/src/features/spatial/three/SpatialStageViewport.tsx",
        "frontend/src/features/spatial/three/SpatialStageViewport.tsx",
        "app.core.spatial_stage.projection.POSTURE_HEIGHT",
        "/api/drama/{task_id}/spatial/scenes/{scene_id}",
        "/api/drama/{task_id}/spatial/scenes/{scene_id}/export",
    ],
    "director-desk": [
        "app.core.spatial_stage.camera_moves.build_keys",
        "app.core.spatial_stage.operations.apply_operations",
        "frontend/src/features/directorDesk/lib/clipExport.ts",
        "app.core.spatial_stage.paths.actor_keys",
        "app.service.director_desk_service.motion_inputs",
        "app.core.spatial_stage.operations.apply_operations",
    ],
    "costage": [
        "app.core.spatial_stage.operations.apply_operations",
        "app.core.spatial_stage.operations.apply_operations",
        "app.core.spatial_stage.geometry.arc_positions",
        "app.core.spatial_stage.coverage.solve_camera",
        "app.core.spatial_stage.validation.check_plan",
        "/api/drama/{task_id}/spatial/scenes/{scene_id}",
        "/api/drama/{task_id}/spatial/scenes/{scene_id}/import",
    ],
}

_EVIDENCE_BY_SOURCE = {
    "minimax-h3-skills": "backend/tests/test_provider_clients.py",
    "drama-skills": "backend/tests/test_preproduction_intelligence.py",
    "facial-expression-prompting": "backend/tests/test_creative_quality.py",
    "visual-skills": "backend/tests/test_continuity.py",
    "dramaclaw": "backend/tests/test_workbench_platform.py",
    "instant-video": "backend/tests/test_production_evidence.py",
    "video-shotcraft": "backend/tests/test_advanced_production.py",
    "fast-movie-ai": "backend/tests/test_drama_pipeline.py",
    "arcreel": "backend/tests/test_screenwriting_engine.py",
    "script-to-shot-engine": "backend/tests/test_production_contracts.py",
    "script-to-video-prompts": "backend/tests/test_script_prompt_pipeline.py",
    "video-agent-skills": "backend/tests/test_advanced_production.py",
    "short-drama-skills": "backend/tests/test_creative_quality.py",
    "sd-2-5-prompt": "backend/tests/test_sd25_prompt_audit.py",
    "fight-prompt-director": "backend/tests/test_fight_prompt_skill.py",
    "fight-video-create-skill": "backend/tests/test_fight_design.py",
    "seedance-2-5-video-director": "backend/tests/test_seedance_video_director_skill.py",
    "storyai-3d-director-desk": "backend/tests/test_spatial_stage_pipeline.py",
    "director-desk": "backend/tests/test_director_desk_repairs.py",
    "costage": "backend/tests/test_spatial_stage.py",
}


def _implementation_status(source_id: str, capability: str, entrypoint: str) -> str:
    if source_id == "video-shotcraft" and capability == "Jianying editable draft export":
        return "interchange-only"
    if source_id == "fight-prompt-director" and capability == "fight scene detection":
        # 场次判定是纯本地词表打分，不经模型；下面的 drama_service 标记按整个类
        # 一刀切成 provider-dependent，对这一条会误报。
        return "implemented"
    if source_id == "seedance-2-5-video-director" and "optimizer" in capability:
        # 导演层本身是本地装载，但它生效的那一步要经过 Seedance/DeepSeek 文本模型改写。
        return "provider-dependent"
    provider_markers = ("/video/", "/audio/", "drama_service", "media_compositor")
    return "provider-dependent" if any(marker in entrypoint for marker in provider_markers) else "implemented"


def _implementations_for(source: CapabilitySource) -> list[dict[str, str]]:
    entrypoints = _IMPLEMENTATION_ENTRYPOINTS.get(source["id"], [])
    if len(entrypoints) != len(source["capabilities"]):
        raise RuntimeError(f"Capability evidence is incomplete for {source['id']}")
    evidence = _EVIDENCE_BY_SOURCE[source["id"]]
    return [
        {
            "capability": label,
            "entrypoint": entrypoint,
            "implementation_status": _implementation_status(source["id"], label, entrypoint),
            "evidence": evidence,
        }
        for label, entrypoint in zip(source["capabilities"], entrypoints, strict=True)
    ]


def capability_implementation_report() -> list[dict]:
    provenance = upstream_source_by_id()
    return [
        {
            "source_id": source["id"],
            "source": source["source"],
            "reviewed_commit": provenance[source["id"]].reviewed_commit,
            "reviewed_at": provenance[source["id"]].reviewed_at,
            "license_observation": provenance[source["id"]].license_observation,
            "code_treatment": provenance[source["id"]].code_treatment,
            "attribution": provenance[source["id"]].attribution,
            "capabilities": list(source["capabilities"]),
            "implementations": _implementations_for(source),
        }
        for source in UPSTREAM_CAPABILITIES
    ]


# Must stay within the persisted column widths in app/platform/models.py
# (CapabilitySetting.capability_id is String(120), command is String(220)).
CAPABILITY_ID_MAX_LENGTH = 120
CAPABILITY_COMMAND_MAX_LENGTH = 220
_SLUG_HASH_LENGTH = 8


def _command_slug(value: str, max_length: int = CAPABILITY_ID_MAX_LENGTH) -> str:
    """Return a stable ASCII identifier suitable for an allowlisted slash command.

    Slugs longer than ``max_length`` are cut at a word boundary and suffixed with
    a short hash of the full slug, so they stay unique and stable across runs.
    """
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-") or "capability"
    if len(normalized) <= max_length:
        return normalized
    digest = hashlib.sha1(normalized.encode()).hexdigest()[:_SLUG_HASH_LENGTH]
    head = normalized[: max_length - _SLUG_HASH_LENGTH - 1]
    if "-" in head:
        head = head.rsplit("-", 1)[0]
    return f"{head.rstrip('-')}-{digest}"


def capability_command_catalog() -> list[dict[str, str]]:
    """Expand all source capabilities into callable, globally switchable records.

    Commands are data-only dispatch identifiers. The catalog never imports or
    executes a module named by a client.
    """
    records: list[dict[str, str]] = []
    for source in UPSTREAM_CAPABILITIES:
        implementations = _implementations_for(source)
        for label, implementation in zip(source["capabilities"], implementations, strict=True):
            capability_id = _command_slug(label)
            command = f"/{_command_slug(source['id'])}.{capability_id}"
            records.append({
                "source_id": source["id"],
                "source_url": source["source"],
                "capability_id": capability_id,
                "label": label,
                "command": command,
                "entrypoint": implementation["entrypoint"],
                "implementation_status": implementation["implementation_status"],
                "evidence": implementation["evidence"],
            })
    too_long = [
        item["command"] for item in records if len(item["command"]) > CAPABILITY_COMMAND_MAX_LENGTH
    ]
    if too_long:
        raise RuntimeError(f"Capability commands exceed {CAPABILITY_COMMAND_MAX_LENGTH} chars: {too_long}")
    if len({item["command"] for item in records}) != len(records):
        raise RuntimeError("Capability command catalog contains duplicate commands")
    return records
