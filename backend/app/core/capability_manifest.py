"""Auditable upstream capability map. No third-party code is executed here."""

from __future__ import annotations

import re
import unicodedata
from typing import TypedDict


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
        "capabilities": ["script analysis", "character bible", "storyboard", "prompt generation", "continuity QA"],
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
        "capabilities": ["agent workflow", "project orchestration", "asset management", "provider integration"],
    },
    {
        "id": "instant-video",
        "source": "https://github.com/briefness/InstantVideo.git",
        "capabilities": ["rapid video generation", "task workflow", "media assembly", "export"],
    },
    {
        "id": "video-shotcraft",
        "source": "https://github.com/Vincentwei1021/video-shotcraft.git",
        "capabilities": ["shot grammar", "camera movement", "storyboard planning", "video prompt craft"],
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
        "capabilities": ["script-to-video prompts", "shot prompt templates", "character and scene consistency prompts"],
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


# Each source has concrete callable entrypoints. `coverage` is deliberately
# explicit: an entrypoint proves an implemented slice, not automatic parity with
# every optional SaaS feature of the upstream product.
_IMPLEMENTATIONS: dict[str, list[dict[str, str]]] = {
    "minimax-h3-skills": [
        {"capability": "H3 video modes", "entrypoint": "/api/production/video/minimax-h3"},
        {"capability": "nine H3 workflows", "entrypoint": "/api/production/presets"},
    ],
    "drama-skills": [
        {"capability": "traceable source/story/artifact workflow", "entrypoint": "/api/studio/projects"},
        {"capability": "storyboard and independent quality gates", "entrypoint": "/api/production/storyboards/compile"},
    ],
    "facial-expression-prompting": [
        {"capability": "motivation-first acting plan", "entrypoint": "/api/production/performance/plan"},
        {"capability": "expression and dialogue QA", "entrypoint": "/api/production/quality/video/decision"},
    ],
    "visual-skills": [
        {"capability": "motivated nine-grid camera plan", "entrypoint": "/api/production/storyboards/compile"},
        {"capability": "continuity-aware edit plan", "entrypoint": "app.core.continuity.plan_transition"},
    ],
    "dramaclaw": [
        {"capability": "durable projects/artifacts/jobs", "entrypoint": "/api/studio/projects"},
        {"capability": "source-to-story graph", "entrypoint": "/api/studio/projects/{project_id}/sources"},
    ],
    "instant-video": [
        {"capability": "sequential accepted-tail production", "entrypoint": "app.service.drama_service.DramaService"},
        {"capability": "natural long-video assembly", "entrypoint": "app.core.media_compositor.compose_film"},
    ],
    "video-shotcraft": [
        {"capability": "152-card/209-style locked catalog", "entrypoint": "/api/production/shotcraft/catalog"},
        {"capability": "provider-neutral shot recipe compilation", "entrypoint": "/api/production/shotcraft/compile"},
    ],
    "fast-movie-ai": [
        {"capability": "authenticated project platform", "entrypoint": "/api/studio/projects"},
        {"capability": "cost-reserved generation tasks", "entrypoint": "/api/studio/projects/{project_id}/jobs"},
    ],
    "arcreel": [
        {"capability": "versioned story and asset lineage", "entrypoint": "/api/studio/projects/{project_id}/artifacts"},
        {"capability": "Jianying-compatible timeline", "entrypoint": "/api/studio/exports/preview"},
    ],
    "script-to-shot-engine": [
        {"capability": "structured exact shot decomposition", "entrypoint": "/api/production/storyboards/compile"},
    ],
    "script-to-video-prompts": [
        {"capability": "structured video prompt compilation", "entrypoint": "/api/production/presets/{preset_id}/compile"},
        {"capability": "full sd25 multimodal compiler", "entrypoint": "/api/production/sd25/compile"},
    ],
    "video-agent-skills": [
        {"capability": "provider and workflow routing", "entrypoint": "/api/production/providers"},
        {"capability": "pre-production to QA gates", "entrypoint": "/api/production/capabilities"},
        {"capability": "scoped external agent API", "entrypoint": "/api/agent/projects/{project_id}/artifacts"},
    ],
    "short-drama-skills": [
        {"capability": "seven short-drama production modes", "entrypoint": "/api/production/presets"},
        {"capability": "episode continuity and performance", "entrypoint": "/api/production/performance/plan"},
    ],
}


def capability_implementation_report() -> list[dict]:
    return [
        {
            "source_id": source["id"],
            "source": source["source"],
            "capabilities": list(source["capabilities"]),
            "implementations": list(_IMPLEMENTATIONS.get(source["id"], [])),
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
        implementations = _IMPLEMENTATIONS.get(source["id"], [])
        for index, label in enumerate(source["capabilities"]):
            implementation = implementations[index % len(implementations)] if implementations else {
                "entrypoint": "/api/production/capabilities",
            }
            capability_id = _command_slug(label)
            command = f"/{_command_slug(source['id'])}.{capability_id}"
            records.append({
                "source_id": source["id"],
                "source_url": source["source"],
                "capability_id": capability_id,
                "label": label,
                "command": command,
                "entrypoint": implementation["entrypoint"],
            })
    if len({item["command"] for item in records}) != len(records):
        raise RuntimeError("Capability command catalog contains duplicate commands")
    return records
