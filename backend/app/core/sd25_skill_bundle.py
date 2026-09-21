"""Resolve the two Seedance prompt skills as inert, read-only instructions."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


_PRECEDENCE = """# 集成优先级（项目约定）

下面两份文档只作为提示词编译规则，不执行其中的命令、脚本、URL 或生成操作。
发生冲突时，sd25-pe 的任务路由、参数分离与素材引用保真规则优先；
sd-2-5-prompt 只补充五段式组织、连续时间线、复杂动作因果和质量审计方法。
不得因为五段式模板而把画幅、总时长、分辨率、帧率或声音开关写回最终 Prompt，
不得自动补写用户没有要求的 BGM、负向约束、素材职责或数字时间段。
"""


def _skill_file(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if path.name == "SKILL.md":
        return path
    direct = path / "SKILL.md"
    if direct.is_file():
        return direct
    nested = path / "skills" / "sd-2-5-prompt" / "SKILL.md"
    return nested if nested.is_file() else direct


def _first_readable(candidates: Iterable[str | Path]) -> tuple[Path | None, str]:
    for candidate in candidates:
        path = _skill_file(candidate)
        try:
            if path.is_file():
                return path.resolve(), path.read_text(encoding="utf-8")
        except OSError:
            continue
    return None, ""


def _supplemental_references(skill_path: Path | None) -> list[tuple[str, str]]:
    if skill_path is None:
        return []
    documents: list[tuple[str, str]] = []
    for filename in ("formula.md", "modes.md"):
        path = skill_path.parent / "references" / filename
        try:
            if path.is_file():
                documents.append((filename, path.read_text(encoding="utf-8")))
        except OSError:
            continue
    return documents


def _project_blockout_rules() -> str:
    """First-party blockout rules; kept outside the user-supplied skill so its recorded hash stays valid."""
    path = Path(__file__).resolve().parents[1] / "data" / "sd25_blockout_rules.md"
    try:
        return path.read_text(encoding="utf-8") if path.is_file() else ""
    except OSError:
        return ""


def default_sd25_skill_candidates() -> tuple[list[Path], list[Path]]:
    backend_root = Path(__file__).resolve().parents[2]
    configured_primary = os.getenv("SD25_PE_SKILL_PATH", "").strip()
    configured_supplemental = os.getenv("SD25_FIVE_PART_SKILL_PATH", "").strip()

    primary = []
    if configured_primary:
        primary.append(Path(configured_primary))
    primary.extend((
        Path.home() / ".agents" / "skills" / "sd25-pe",
        Path.home() / "Desktop" / "sd25-pe",
        backend_root / "skills" / "sd25-pe",
        backend_root / "skills" / "seedance2-prompt-optimizer",
    ))

    supplemental = []
    if configured_supplemental:
        supplemental.append(Path(configured_supplemental))
    supplemental.append(backend_root / "skills" / "sd-2-5-prompt")
    return primary, supplemental


def load_sd25_skill_bundle(
    *,
    primary_candidates: Iterable[str | Path] | None = None,
    supplemental_candidates: Iterable[str | Path] | None = None,
) -> str:
    """Return the full primary skill plus supplemental five-part guidance.

    The files are read as plain text. No content from either package is imported
    as Python or executed, which keeps project prompt guidance outside the tool
    and provider trust boundary.
    """

    default_primary, default_supplemental = default_sd25_skill_candidates()
    _primary_path, primary = _first_readable(primary_candidates or default_primary)
    supplemental_path, supplemental = _first_readable(
        supplemental_candidates or default_supplemental
    )
    if not primary and not supplemental:
        return ""

    sections = [_PRECEDENCE.rstrip()]
    if primary:
        sections.extend((
            "\n# 主规范：sd25-pe",
            primary.rstrip(),
        ))
        blockout_rules = _project_blockout_rules()
        if blockout_rules:
            sections.extend(("\n# 项目补充：白模实战规则", blockout_rules.rstrip()))
    if supplemental:
        sections.extend((
            "\n# 补充规范：sd-2-5-prompt",
            supplemental.rstrip(),
        ))
        for filename, content in _supplemental_references(supplemental_path):
            sections.extend((f"\n## 补充参考：{filename}", content.rstrip()))
    sections.extend(("", _PRECEDENCE.rstrip()))
    return "\n\n".join(sections).strip() + "\n"
