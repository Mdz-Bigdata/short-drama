#!/usr/bin/env python3
"""Deterministic structural validation for the public Skill repository."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_NAME = "seedance-2-5-video-director"


def fail(message: str, errors: list[str]) -> None:
    errors.append(message)


def validate_required_files(errors: list[str]) -> None:
    required = [
        "SKILL.md",
        "README.md",
        "LICENSE",
        "NOTICE.md",
        "agents/openai.yaml",
        "references/capabilities-and-limits.md",
        "references/first-use-onboarding.md",
        "references/multimodal-patterns.md",
        "references/official-examples.md",
        "references/prompt-blueprints.md",
        "references/realistic-direction-patterns.md",
        "tests/cases.json",
        ".github/workflows/validate.yml",
    ]
    for relative in required:
        if not (ROOT / relative).is_file():
            fail(f"missing required file: {relative}", errors)


def validate_skill_frontmatter(errors: list[str]) -> None:
    text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        fail("SKILL.md must start with YAML frontmatter", errors)
        return
    parts = text.split("---", 2)
    if len(parts) < 3:
        fail("SKILL.md frontmatter is not closed", errors)
        return
    frontmatter = parts[1]
    name_match = re.search(r"(?m)^name:\s*(.+?)\s*$", frontmatter)
    description_match = re.search(r"(?m)^description:\s*(.+?)\s*$", frontmatter)
    if not name_match or name_match.group(1).strip('"\'') != SKILL_NAME:
        fail(f"SKILL.md name must be {SKILL_NAME}", errors)
    if not description_match or len(description_match.group(1).strip()) < 80:
        fail("SKILL.md description is missing or too short", errors)
    required_phrases = [
        "Installation onboarding protocol",
        "references/first-use-onboarding.md",
        "A new conversation or the Skill's first invocation in a conversation is not evidence of a new installation",
    ]
    for phrase in required_phrases:
        if phrase not in text:
            fail(f"SKILL.md missing first-use contract: {phrase}", errors)


def validate_onboarding(errors: list[str]) -> None:
    text = (ROOT / "references/first-use-onboarding.md").read_text(encoding="utf-8")
    for heading in ("## 学习指导", "## 最小输入模板", "## 学习示例"):
        if heading not in text:
            fail(f"onboarding missing section: {heading}", errors)
    if text.count("### 示例") < 4:
        fail("onboarding must contain at least four learning examples", errors)
    if f"${SKILL_NAME}" not in text:
        fail("onboarding minimal template must invoke the Skill by name", errors)
    if "当前会话首次调用时" in text:
        fail("onboarding must not trigger merely on the first invocation of a conversation", errors)


def validate_markdown_links(errors: list[str]) -> None:
    link_pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    for markdown in ROOT.rglob("*.md"):
        text = markdown.read_text(encoding="utf-8")
        for target in link_pattern.findall(text):
            target = target.strip().split("#", 1)[0]
            if not target or "://" in target or target.startswith("#"):
                continue
            resolved = (markdown.parent / target).resolve()
            try:
                resolved.relative_to(ROOT.resolve())
            except ValueError:
                fail(f"link escapes repository: {markdown.relative_to(ROOT)} -> {target}", errors)
                continue
            if not resolved.exists():
                fail(f"broken link: {markdown.relative_to(ROOT)} -> {target}", errors)


def validate_agent_metadata(errors: list[str]) -> None:
    text = (ROOT / "agents/openai.yaml").read_text(encoding="utf-8")
    if f"${SKILL_NAME}" not in text:
        fail("agents/openai.yaml default_prompt must mention the Skill", errors)
    if "display_name:" not in text or "short_description:" not in text:
        fail("agents/openai.yaml is missing interface metadata", errors)


def validate_cases(errors: list[str]) -> None:
    path = ROOT / "tests/cases.json"
    try:
        cases = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"invalid tests/cases.json: {exc}", errors)
        return
    if not isinstance(cases, list) or len(cases) < 10:
        fail("tests/cases.json must contain at least ten cases", errors)
        return
    ids: set[str] = set()
    categories: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            fail(f"case {index} must be an object", errors)
            continue
        for field in ("id", "category", "request", "expected"):
            if field not in case:
                fail(f"case {index} missing field: {field}", errors)
        case_id = case.get("id")
        if isinstance(case_id, str):
            if case_id in ids:
                fail(f"duplicate case id: {case_id}", errors)
            ids.add(case_id)
        category = case.get("category")
        if isinstance(category, str):
            categories.add(category)
        expected = case.get("expected")
        if not isinstance(expected, list) or not expected:
            fail(f"case {case_id or index} expected must be a non-empty list", errors)
    required_categories = {
        "onboarding",
        "basic-multimodal",
        "timestamp-30s",
        "long-video",
        "video-extension",
        "video-edit",
        "clay-renderer",
        "seamless-transition",
        "multi-grid-storyboard",
        "diagnosis",
    }
    missing = sorted(required_categories - categories)
    if missing:
        fail(f"test categories missing: {', '.join(missing)}", errors)


def validate_no_placeholders(errors: list[str]) -> None:
    placeholder = re.compile(r"\b(TODO|TBD|FIXME)\b", re.IGNORECASE)
    for path in [ROOT / "SKILL.md", ROOT / "README.md", *ROOT.joinpath("references").glob("*.md")]:
        match = placeholder.search(path.read_text(encoding="utf-8"))
        if match:
            fail(f"placeholder {match.group(0)} found in {path.relative_to(ROOT)}", errors)


def main() -> int:
    errors: list[str] = []
    validate_required_files(errors)
    if not errors:
        validate_skill_frontmatter(errors)
        validate_onboarding(errors)
        validate_markdown_links(errors)
        validate_agent_metadata(errors)
        validate_cases(errors)
        validate_no_placeholders(errors)
    if errors:
        print("Validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Validation passed: repository structure, onboarding, links, metadata, and test contracts are valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
