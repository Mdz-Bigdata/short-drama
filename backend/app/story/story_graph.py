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


class StoryGraphBuilder:
    _DIALOGUE = re.compile(r"(?m)^\s*([\u4e00-\u9fffA-Za-z][\w\u4e00-\u9fff·.-]{0,19})\s*[:：]")
    _SCENE_CN = re.compile(r"(?m)^\s*(?:#+\s*)?场景\s*[:：]\s*([^\n]+)")
    _SCENE_FDX = re.compile(r"(?im)^\s*(?:(?:INT|EXT|INT\.?/EXT|I/E)\.?\s+[^\n]+)")
    _RESERVED = {"场景", "地点", "时间", "动作", "旁白", "音效", "音乐", "镜头"}

    def build(self, document: SourceDocument) -> StoryGraph:
        character_spans: dict[str, list[str]] = {}
        scene_spans: dict[str, list[str]] = {}
        events: list[StoryEvent] = []

        for order, span in enumerate(document.spans, start=1):
            for name in self._DIALOGUE.findall(span.text):
                clean = name.strip("# ")
                if clean not in self._RESERVED:
                    character_spans.setdefault(clean, []).append(span.id)
            for name in self._SCENE_CN.findall(span.text):
                scene_spans.setdefault(name.strip(), []).append(span.id)
            for match in self._SCENE_FDX.findall(span.text):
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
