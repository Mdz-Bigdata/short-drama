# -*- coding: utf-8 -*-
"""Production knowledge, found through the skills that own it.

Every guide the pipeline reads lives inside a skill, and every skill that carries knowledge says
so in a ``manifest.json`` beside its ``SKILL.md``::

    {
      "version": 1,
      "sections": [
        {"key": "<section-key>", "title": "<the guide's title>",
         "file": "references/<file>", "budget": 5000, "stages": [1, 2]}
      ]
    }

``key`` is how code asks for the section; ``file`` is relative to the skill and must stay inside
it; ``budget`` is the default character budget (0 = the whole text); ``stages`` are the pipeline
stages whose prompts take it. ``scope`` is ``"knowledge"`` (the default: production knowledge the
stages read and the agent council fingerprints) or ``"skill"`` (a reference that only the skill's
own loader reads, e.g. shot-design-master's grammar tables); keys are unique across both. Nothing in Python names a guide's file or path: a guide is moved,
renamed or added by editing a manifest (or by ``scripts/organize_knowledge.py``, which writes them).

The manifest file is project metadata, so a vendored skill can carry one without its upstream
files being touched.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app import settings

logger = logging.getLogger("app.core.knowledge_registry")

MANIFEST_NAME = "manifest.json"
MANIFEST_VERSION = 1
_KEY = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
_MAX_STAGE = 8
SCOPES = ("knowledge", "skill")


class KnowledgeManifestError(ValueError):
    """A skill manifest that cannot be honoured: a duplicate key, a file outside the skill, a bad field."""


@dataclass(frozen=True)
class KnowledgeSection:
    key: str
    title: str
    skill: str
    path: Path
    budget: int
    stages: tuple[int, ...]
    scope: str = "knowledge"

    @property
    def relative_path(self) -> str:
        """Path from the skills root: ``<skill>/<file>``."""
        return self.path.relative_to(settings.skills_root().resolve()).as_posix()


def skills_root() -> Path:
    return settings.skills_root().resolve()


def _section(skill_dir: Path, skill: str, raw: object, index: int) -> KnowledgeSection:
    where = f"{skill}/{MANIFEST_NAME} sections[{index}]"
    if not isinstance(raw, Mapping):
        raise KnowledgeManifestError(f"{where} 必须是对象")
    key = str(raw.get("key") or "")
    if not _KEY.fullmatch(key):
        raise KnowledgeManifestError(f"{where} 的 key {key!r} 不合法：小写字母、数字与连字符，2–64 个字符")
    title = str(raw.get("title") or "").strip()
    if not title:
        raise KnowledgeManifestError(f"{where} 缺少 title")
    relative = str(raw.get("file") or "")
    target = (skill_dir / relative).resolve()
    if not relative or (target != skill_dir and skill_dir not in target.parents):
        raise KnowledgeManifestError(f"{where} 的 file {relative!r} 必须是技能目录内的相对路径")
    budget = raw.get("budget", 0)
    if isinstance(budget, bool) or not isinstance(budget, int) or budget < 0:
        raise KnowledgeManifestError(f"{where} 的 budget 必须是非负整数")
    stages = raw.get("stages", [])
    if not isinstance(stages, list) or any(
        isinstance(stage, bool) or not isinstance(stage, int) or not 1 <= stage <= _MAX_STAGE for stage in stages
    ):
        raise KnowledgeManifestError(f"{where} 的 stages 必须是 1–{_MAX_STAGE} 的阶段号列表")
    scope = str(raw.get("scope") or "knowledge")
    if scope not in SCOPES:
        raise KnowledgeManifestError(f"{where} 的 scope 只能是 {' / '.join(SCOPES)}")
    if scope == "skill" and stages:
        raise KnowledgeManifestError(f"{where} 是技能内部参考（scope=skill），不能登记阶段")
    return KnowledgeSection(
        key=key, title=title, skill=skill, path=target, budget=budget, stages=tuple(sorted(set(stages))), scope=scope,
    )


def _read_manifest(skill_dir: Path) -> list[KnowledgeSection]:
    path = skill_dir / MANIFEST_NAME
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise KnowledgeManifestError(f"{skill_dir.name}/{MANIFEST_NAME} 无法读取：{error}") from error
    if not isinstance(payload, Mapping) or payload.get("version") != MANIFEST_VERSION:
        raise KnowledgeManifestError(f"{skill_dir.name}/{MANIFEST_NAME} 的 version 必须是 {MANIFEST_VERSION}")
    sections = payload.get("sections", [])
    if not isinstance(sections, list):
        raise KnowledgeManifestError(f"{skill_dir.name}/{MANIFEST_NAME} 的 sections 必须是列表")
    return [_section(skill_dir.resolve(), skill_dir.name, raw, index) for index, raw in enumerate(sections)]


@lru_cache(maxsize=4)
def _index(root: str) -> dict[str, KnowledgeSection]:
    base = Path(root)
    found: dict[str, KnowledgeSection] = {}
    if not base.is_dir():
        logger.warning("[Knowledge] 技能目录不存在: %s", base)
        return found
    for manifest in sorted(base.glob(f"*/{MANIFEST_NAME}")):
        for section in _read_manifest(manifest.parent):
            if section.key in found:
                other = found[section.key]
                raise KnowledgeManifestError(f"知识章节 {section.key!r} 同时登记在 {other.skill} 与 {section.skill}")
            found[section.key] = section
    return found


def sections() -> dict[str, KnowledgeSection]:
    """Every production-knowledge section (scope ``knowledge``) by key."""
    return {key: item for key, item in _index(str(skills_root())).items() if item.scope == "knowledge"}


def skill_sections(skill: str) -> dict[str, KnowledgeSection]:
    """One skill's own references (scope ``skill``) by key, in manifest order."""
    return {key: item for key, item in _index(str(skills_root())).items() if item.skill == skill and item.scope == "skill"}


def section(key: str) -> KnowledgeSection | None:
    """Any registered section by key, whatever its scope."""
    return _index(str(skills_root())).get(key)


def stage_sections() -> dict[int, tuple[str, ...]]:
    """Stage → the keys of the sections its prompts take, in registration order."""
    matrix: dict[int, list[str]] = {stage: [] for stage in range(1, _MAX_STAGE + 1)}
    for item in sections().values():
        for stage in item.stages:
            matrix[stage].append(item.key)
    return {stage: tuple(keys) for stage, keys in matrix.items()}


def section_title(key: str) -> str:
    """The guide's title, for prose that cites it; the key itself when the section is unknown."""
    found = section(key)
    return found.title if found else key


def reset() -> None:
    """Forget the index (tests, a moved ``SKILLS_DIR``, a manifest edited at runtime)."""
    _index.cache_clear()


__all__ = [
    "MANIFEST_NAME", "MANIFEST_VERSION", "SCOPES", "KnowledgeManifestError", "KnowledgeSection", "reset", "section",
    "section_title", "sections", "skill_sections", "skills_root", "stage_sections",
]
