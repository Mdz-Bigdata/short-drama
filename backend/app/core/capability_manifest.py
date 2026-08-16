"""Auditable upstream capability map. No third-party code is executed here."""

from __future__ import annotations

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
        "capabilities": ["story graph", "shot generation", "asset/reference management", "render workflow", "timeline"],
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
    "arcreel": "backend/tests/test_workbench_platform.py",
    "script-to-shot-engine": "backend/tests/test_production_contracts.py",
    "script-to-video-prompts": "backend/tests/test_script_prompt_pipeline.py",
    "video-agent-skills": "backend/tests/test_advanced_production.py",
    "short-drama-skills": "backend/tests/test_creative_quality.py",
}


def _implementation_status(source_id: str, capability: str, entrypoint: str) -> str:
    if source_id == "video-shotcraft" and capability == "Jianying editable draft export":
        return "interchange-only"
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


def _command_slug(value: str) -> str:
    """Return a stable ASCII identifier suitable for an allowlisted slash command."""
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return normalized or "capability"


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
    if len({item["command"] for item in records}) != len(records):
        raise RuntimeError("Capability command catalog contains duplicate commands")
    return records
