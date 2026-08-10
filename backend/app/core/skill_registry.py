"""Read-only skill discovery with safe names and explicit prompt-compiler routing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


_SAFE_NAME = re.compile(r"^[\w.-]+$", re.UNICODE)


@dataclass(frozen=True)
class LoadedSkill:
    name: str
    description: str
    kind: str
    path: Path
    instructions: str


class SkillRegistry:
    def __init__(self, roots: list[Path]):
        self.roots = [Path(root).expanduser().resolve() for root in roots]
        self._skills: dict[str, LoadedSkill] | None = None

    @staticmethod
    def _front_matter(text: str) -> tuple[str, str]:
        if not text.startswith("---"):
            return "", ""
        block = text.split("---", 2)[1]
        name_match = re.search(r"(?m)^name:\s*['\"]?([^'\"\n]+)", block)
        description_match = re.search(r"(?m)^description:\s*['\"]?([^'\"\n]+)", block)
        return (
            name_match.group(1).strip() if name_match else "",
            description_match.group(1).strip() if description_match else "",
        )

    @staticmethod
    def _kind(name: str, text: str) -> str:
        lowered = f"{name}\n{text[:1200]}".lower()
        if "prompt optimizer" in lowered or "提示词" in lowered or name == "sd25-pe":
            return "prompt_compiler"
        if "storyboard" in lowered or "分镜" in lowered:
            return "storyboard"
        return "workflow"

    def _discover(self) -> dict[str, LoadedSkill]:
        skills: dict[str, LoadedSkill] = {}
        for root in self.roots:
            if not root.exists():
                continue
            candidates = [root / "SKILL.md"] if (root / "SKILL.md").is_file() else []
            candidates.extend(root.glob("*/SKILL.md"))
            candidates.extend(root.glob("*/*/SKILL.md"))
            for path in sorted(set(candidates)):
                resolved = path.resolve()
                if root != resolved.parent and root not in resolved.parents:
                    continue
                text = resolved.read_text(encoding="utf-8", errors="replace")
                front_name, description = self._front_matter(text)
                name = front_name or resolved.parent.name
                if not _SAFE_NAME.fullmatch(name):
                    continue
                skills[name] = LoadedSkill(
                    name=name,
                    description=description,
                    kind=self._kind(name, text),
                    path=resolved,
                    instructions=text,
                )
        return skills

    def list(self) -> list[LoadedSkill]:
        if self._skills is None:
            self._skills = self._discover()
        return sorted(self._skills.values(), key=lambda item: item.name)

    def get(self, name: str) -> LoadedSkill:
        if not _SAFE_NAME.fullmatch(name or ""):
            raise ValueError("invalid skill name")
        if self._skills is None:
            self._skills = self._discover()
        try:
            return self._skills[name]
        except KeyError as exc:
            raise KeyError(f"skill not found: {name}") from exc
