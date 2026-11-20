"""Deterministic, evidence-linked story graph extraction.

This layer only promotes explicit source text to facts. Creative inference belongs
in a separately versioned adaptation artifact.
"""

from __future__ import annotations

import re
import uuid

from app.schema.studio import (
    SourceDocument,
    StoryCharacter,
    StoryEvent,
    StoryGraph,
    StoryScene,
)
from app.core import prompt_data


_WORDING_FILE = "story_story_graph"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/story_story_graph.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)


class StoryGraphBuilder:
    _DIALOGUE = re.compile(r"(?m)^\s*([\u4e00-\u9fffA-Za-z][\w\u4e00-\u9fff·.-]{0,19})\s*[:：]")
    _SCENE_CN = re.compile(_text_of("StoryGraphBuilder.scene_cn"))
    _SCENE_FDX = re.compile(r"(?im)^\s*(?:(?:INT|EXT|INT\.?/EXT|I/E)\.?\s+[^\n]+)")
    _SCENE_CN_SIDE = re.compile(_text_of("StoryGraphBuilder.scene_cn_side"))
    _SCENE_CN_NUMBERED = re.compile(_text_of("StoryGraphBuilder.scene_cn_numbered"))
    # Spaced names ("MARY JANE: …") only count in capitals, so an action line with a colon stays an action line.
    _DIALOGUE_SPACED = re.compile(r"(?m)^\s*([A-Z][A-Z0-9._-]*(?: [A-Z0-9._-]+)+)\s*[:：][ \t]*\S")
    _RESERVED = {_text_of("StoryGraphBuilder.reserved"), _text_of("StoryGraphBuilder.reserved.2"), _text_of("StoryGraphBuilder.reserved.3"), _text_of("StoryGraphBuilder.reserved.4"), _text_of("StoryGraphBuilder.reserved.5"), _text_of("StoryGraphBuilder.reserved.6"), _text_of("StoryGraphBuilder.reserved.7"), _text_of("StoryGraphBuilder.reserved.8"), _text_of("StoryGraphBuilder.reserved.9"), _text_of("StoryGraphBuilder.reserved.10"), _text_of("StoryGraphBuilder.reserved.11"), _text_of("StoryGraphBuilder.reserved.12"), _text_of("StoryGraphBuilder.reserved.13"), _text_of("StoryGraphBuilder.reserved.14"), _text_of("StoryGraphBuilder.reserved.15")}

    def build(self, document: SourceDocument) -> StoryGraph:
        character_spans: dict[str, list[str]] = {}
        scene_spans: dict[str, list[str]] = {}
        events: list[StoryEvent] = []

        for order, span in enumerate(document.spans, start=1):
            for name in self._DIALOGUE.findall(span.text):
                clean = name.strip("# ")
                if clean not in self._RESERVED:
                    character_spans.setdefault(clean, []).append(span.id)
            for name in self._DIALOGUE_SPACED.findall(span.text):
                character_spans.setdefault(name.strip(), []).append(span.id)
            for name in self._SCENE_CN.findall(span.text):
                scene_spans.setdefault(name.strip(), []).append(span.id)
            for pattern in (self._SCENE_FDX, self._SCENE_CN_SIDE, self._SCENE_CN_NUMBERED):
                for match in pattern.findall(span.text):
                    scene_spans.setdefault(match.strip(), []).append(span.id)
            summary = re.sub(r"\s+", " ", span.text).strip()
            if summary:
                events.append(StoryEvent(
                    id=f"evt_{uuid.uuid4().hex}", summary=summary[:500], order=order,
                    evidence_span_ids=[span.id], source_fact=True,
                ))

        return StoryGraph(
            source_id=document.id,
            characters=[
                StoryCharacter(
                    id=f"char_{uuid.uuid5(uuid.NAMESPACE_URL, document.id + name).hex}",
                    name=name, evidence_span_ids=list(dict.fromkeys(span_ids)),
                )
                for name, span_ids in character_spans.items()
            ],
            scenes=[
                StoryScene(
                    id=f"scene_{uuid.uuid5(uuid.NAMESPACE_URL, document.id + name).hex}",
                    name=name, evidence_span_ids=list(dict.fromkeys(span_ids)),
                )
                for name, span_ids in scene_spans.items()
            ],
            events=events,
        )
