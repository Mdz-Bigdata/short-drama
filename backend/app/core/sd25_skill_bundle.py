"""Resolve the two Seedance prompt skills as inert, read-only instructions."""

from __future__ import annotations

import os
from pathlib import Path

from app import settings
from typing import Iterable
from app.core import prompt_data


_WORDING_FILE = "sd25_skill_bundle"


def _text_of(key: str) -> str:
    """Wording kept in app/data/prompt/sd25_skill_bundle.json."""
    return prompt_data.text(_WORDING_FILE, key)


def _words_of(key: str) -> tuple[str, ...]:
    return prompt_data.words(_WORDING_FILE, key)


_PRECEDENCE = _text_of("module.precedence")


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


BUNDLED_SKILLS_DIR = settings.skills_root()
PRIMARY_SKILL_ENV = "SD25_PE_SKILL_PATH"
SUPPLEMENTAL_SKILL_ENV = "SD25_FIVE_PART_SKILL_PATH"


def _configured_skill_path(variable: str) -> Path | None:
    configured = os.getenv(variable, "").strip()
    return Path(configured) if configured else None


def _user_installed_primary_skills() -> tuple[Path, ...]:
    """Where a user-installed sd25-pe is looked for when no path is configured."""
    return (
        Path.home() / ".agents" / "skills" / "sd25-pe",
        Path.home() / "Desktop" / "sd25-pe",
    )


def default_sd25_skill_candidates() -> tuple[list[Path], list[Path]]:
    configured_primary = _configured_skill_path(PRIMARY_SKILL_ENV)
    configured_supplemental = _configured_skill_path(SUPPLEMENTAL_SKILL_ENV)

    primary = [configured_primary] if configured_primary else []
    primary.extend(_user_installed_primary_skills())
    primary.extend((
        BUNDLED_SKILLS_DIR / "sd25-pe",
        BUNDLED_SKILLS_DIR / "seedance2-prompt-optimizer",
    ))

    supplemental = [configured_supplemental] if configured_supplemental else []
    supplemental.append(BUNDLED_SKILLS_DIR / "sd-2-5-prompt")
    return primary, supplemental


def skill_registry_roots() -> list[Path]:
    """Directories the skill registry lists: bundled skills plus the external SD 2.5 ones.

    A configured path replaces the user-install locations rather than joining them.
    """
    configured_primary = _configured_skill_path(PRIMARY_SKILL_ENV)
    configured_supplemental = _configured_skill_path(SUPPLEMENTAL_SKILL_ENV)
    primary = [configured_primary.expanduser()] if configured_primary else list(_user_installed_primary_skills())
    supplemental = [configured_supplemental.expanduser()] if configured_supplemental else []
    return [BUNDLED_SKILLS_DIR, *primary, *supplemental]


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
            _text_of("load_sd25_skill_bundle.text"),
            primary.rstrip(),
        ))
        blockout_rules = _project_blockout_rules()
        if blockout_rules:
            sections.extend((_text_of("load_sd25_skill_bundle.text.2"), blockout_rules.rstrip()))
    if supplemental:
        sections.extend((
            _text_of("load_sd25_skill_bundle.text.3"),
            supplemental.rstrip(),
        ))
        for filename, content in _supplemental_references(supplemental_path):
            sections.extend((_text_of("load_sd25_skill_bundle.text.4").format(filename), content.rstrip()))
    sections.extend(("", _PRECEDENCE.rstrip()))
    return "\n\n".join(sections).strip() + "\n"
