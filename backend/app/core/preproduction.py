"""Deterministic, source-bound pre-production helpers.

Creative judgments remain reviewable artifacts. This module only performs the
mechanical indexing, hashing, reproducible sampling and voice-reference gates.
"""

from __future__ import annotations

import hashlib
import re

from app.schema.intelligence import (
    ChapterSlice,
    EpisodeBoundary,
    EpisodeIntakeReport,
    EpisodeIntakeRequest,
    EpisodeSlice,
    NovelAnalysisReport,
    NovelAnalyzeRequest,
    VoiceCastingPlan,
    VoiceDirectionRequest,
)


_CHAPTER_HEADING = re.compile(
    r"^\s*(?:第[零〇一二三四五六七八九十百千万两\d]+[章回节卷]|chapter\s+[0-9ivxlcdm]+)\b.*$",
    re.IGNORECASE,
)
_EPISODE_HEADING = re.compile(
    r"^\s*(?:第[零〇一二三四五六七八九十百千万两\d]+集|ep(?:isode)?\s*[-_ ]?\d+)\b.*$",
    re.IGNORECASE,
)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _line_offsets(text: str) -> tuple[list[str], list[int], list[int]]:
    lines = text.splitlines(keepends=True)
    if not lines:
        lines = [text]
    char_offsets = [0]
    byte_offsets = [0]
    for line in lines:
        char_offsets.append(char_offsets[-1] + len(line))
        byte_offsets.append(byte_offsets[-1] + len(line.encode("utf-8")))
    return lines, char_offsets, byte_offsets


def _even_sample_indices(total: int, requested: int) -> list[int]:
    count = min(total, requested)
    if count <= 0:
        return []
    if count == 1:
        return [1]
    selected = {
        round(index * (total - 1) / (count - 1)) + 1
        for index in range(count)
    }
    return sorted(selected)


class PreproductionPlanner:
    def analyze_novel(self, request: NovelAnalyzeRequest) -> NovelAnalysisReport:
        lines, char_offsets, byte_offsets = _line_offsets(request.text)
        headings = [index for index, line in enumerate(lines) if _CHAPTER_HEADING.match(line.strip())]
        warnings: list[str] = []
        if not headings:
            headings = [0]
            warnings.append("no chapter headings detected; the complete source is indexed as one chapter")

        chapters: list[ChapterSlice] = []
        for ordinal, start_line in enumerate(headings, start=1):
            end_line = headings[ordinal] if ordinal < len(headings) else len(lines)
            start_char = char_offsets[start_line]
            end_char = char_offsets[end_line]
            chapter_text = request.text[start_char:end_char]
            title = lines[start_line].strip() if len(headings) > 1 or _CHAPTER_HEADING.match(lines[start_line].strip()) else "全文"
            chapters.append(ChapterSlice(
                index=ordinal,
                title=title[:300],
                start_char=start_char,
                end_char=end_char,
                start_byte=byte_offsets[start_line],
                end_byte=byte_offsets[end_line],
                sha256=_sha256(chapter_text),
                character_count=len(chapter_text),
            ))

        sampled = _even_sample_indices(len(chapters), request.sample_count)
        sampled_bytes = sum(
            chapters[index - 1].end_byte - chapters[index - 1].start_byte
            for index in sampled
        )
        total_bytes = max(1, len(request.text.encode("utf-8")))
        return NovelAnalysisReport(
            source_id=request.source_id,
            content_sha256=_sha256(request.text),
            chapters=chapters,
            sampled_chapter_indices=sampled,
            coverage_ratio=round(sampled_bytes / total_bytes, 6),
            warnings=warnings,
        )

    def index_episodes(self, request: EpisodeIntakeRequest) -> EpisodeIntakeReport:
        lines, _char_offsets, byte_offsets = _line_offsets(request.text)
        warnings: list[str] = []
        boundaries = list(request.boundaries)
        if not boundaries:
            starts = [index for index, line in enumerate(lines) if _EPISODE_HEADING.match(line.strip())]
            if not starts:
                starts = [0]
                warnings.append("no episode headings detected; explicit creator-approved boundaries are recommended")
            boundaries = [
                EpisodeBoundary(
                    episode_index=position + 1,
                    title=(lines[start].strip() or f"第 {position + 1} 集")[:200],
                    start_line=start + 1,
                    end_line=(starts[position + 1] if position + 1 < len(starts) else len(lines)),
                )
                for position, start in enumerate(starts)
            ]

        if any(boundary.end_line > len(lines) for boundary in boundaries):
            raise ValueError("episode line boundary exceeds the source line count")

        episodes: list[EpisodeSlice] = []
        for boundary in sorted(boundaries, key=lambda item: item.episode_index):
            start_index = boundary.start_line - 1
            end_index = boundary.end_line
            episode_text = "".join(lines[start_index:end_index])
            episodes.append(EpisodeSlice(
                episode_index=boundary.episode_index,
                title=boundary.title,
                start_line=boundary.start_line,
                end_line=boundary.end_line,
                start_byte=byte_offsets[start_index],
                end_byte=byte_offsets[end_index],
                sha256=_sha256(episode_text),
                text=episode_text,
            ))

        return EpisodeIntakeReport(
            source_id=request.source_id,
            content_sha256=_sha256(request.text),
            output_language=request.output_language,
            prompt_language=request.prompt_language,
            episodes=episodes,
            pending_episode_indices=[
                item.episode_index for item in episodes
                if item.episode_index > request.resume_after_episode
            ],
            warnings=warnings,
        )

    @staticmethod
    def plan_voice(request: VoiceDirectionRequest) -> VoiceCastingPlan:
        reference = request.reference
        status = (
            "needs_reference" if reference is None
            else "ready" if reference.admission_status == "approved"
            else "blocked" if reference.admission_status == "rejected"
            else "needs_review"
        )
        warnings = []
        if reference is None:
            warnings.append("voice identity remains unbound until an authorized reference is selected")
        elif reference.admission_status == "unverified":
            warnings.append("binding does not prove the reference was reviewed or authorized for this use")
        return VoiceCastingPlan(
            character_id=request.character_id,
            character_name=request.character_name,
            language=request.language,
            status=status,
            reference=reference,
            selection_criteria=request.selection_criteria,
            rejection_criteria=request.rejection_criteria,
            pronunciations=request.pronunciations,
            warnings=warnings,
        )
