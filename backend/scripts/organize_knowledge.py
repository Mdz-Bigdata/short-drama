#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""File loose Markdown guides into the skills that own them.

Reads ``<skills>/knowledge-routing.json``. A guide named in ``documents`` goes to that skill
under the key and target given there; any other guide is routed by ``rules`` — the first rule
whose words appear in its file name or first heading wins, and a rule with no words catches the
rest. Each move is recorded in the skill's ``manifest.json`` (created when missing), which is all
the runtime reads (``app/core/knowledge_registry.py``).

Safe to run again: a guide already in place is skipped; a source identical to its target is
removed; a source that differs from an existing target is left alone and reported unless
``--replace`` is given.

    python scripts/organize_knowledge.py              # file everything at the repository root
    python scripts/organize_knowledge.py --dry-run    # say what would happen
    python scripts/organize_knowledge.py --source some/dir
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app import settings  # noqa: E402
from app.core.knowledge_registry import MANIFEST_NAME, MANIFEST_VERSION  # noqa: E402

ROUTING_NAME = "knowledge-routing.json"


def _heading(path: Path) -> str:
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[:40]:
        if line.startswith("#"):
            return line.lstrip("#").strip()
    return ""


def _route(path: Path, routing: dict) -> dict | None:
    for entry in routing.get("documents", []):
        if entry["file"] == path.name:
            return dict(entry)
    probe = f"{path.stem} {_heading(path)}"
    for rule in routing.get("rules", []):
        words = rule.get("words") or []
        if not words or any(word in probe for word in words):
            # A guide nobody named gets a stable key from its title, so a re-run lands it in the same place.
            key = "guide-" + hashlib.sha1(path.stem.encode("utf-8")).hexdigest()[:8]
            return {
                "file": path.name, "skill": rule["skill"], "key": key, "title": path.stem,
                "target": f"references/{key}.md", "budget": rule.get("budget", 5000), "stages": rule.get("stages", []),
            }
    return None


def _load_manifest(skill_dir: Path) -> dict:
    path = skill_dir / MANIFEST_NAME
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"version": MANIFEST_VERSION, "sections": []}


def _register(skill_dir: Path, entry: dict, dry_run: bool) -> None:
    manifest = _load_manifest(skill_dir)
    section = {
        "key": entry["key"], "title": entry["title"], "file": entry["target"],
        "budget": entry["budget"], "stages": entry["stages"],
    }
    kept = [item for item in manifest.get("sections", []) if item.get("key") != entry["key"]]
    manifest["sections"] = [*kept, section]
    if not dry_run:
        (skill_dir / MANIFEST_NAME).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _move(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    # git mv keeps the guide's history; outside a work tree a plain move does.
    moved = subprocess.run(["git", "mv", "-k", str(source), str(target)], capture_output=True, cwd=source.parent)
    if moved.returncode != 0 or source.exists():
        shutil.move(str(source), str(target))


def organize(source_dir: Path, skills_dir: Path, *, dry_run: bool = False, replace: bool = False) -> list[str]:
    routing = json.loads((skills_dir / ROUTING_NAME).read_text(encoding="utf-8"))
    keep = set(routing.get("keep", []))
    report: list[str] = []
    for path in sorted(source_dir.glob("*.md")):
        if path.name in keep:
            continue
        entry = _route(path, routing)
        if entry is None:
            report.append(f"未归类  {path.name}：没有匹配的路由规则")
            continue
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,63}", entry["key"]):
            report.append(f"跳过    {path.name}：路由给出的 key {entry['key']!r} 不合法")
            continue
        skill_dir = skills_dir / entry["skill"]
        if not (skill_dir / "SKILL.md").is_file():
            report.append(f"跳过    {path.name}：技能 {entry['skill']} 不存在")
            continue
        target = skill_dir / entry["target"]
        if target.exists():
            same = target.read_bytes() == path.read_bytes()
            if not same and not replace:
                report.append(f"冲突    {path.name} 与 {entry['skill']}/{entry['target']} 内容不同；核对后用 --replace 覆盖")
                continue
            if not dry_run:
                if same:
                    path.unlink()
                else:
                    target.unlink()
                    _move(path, target)
            report.append(f"{'已去重' if same else '已覆盖'}  {path.name} → {entry['skill']}/{entry['target']}")
        else:
            if not dry_run:
                _move(path, target)
            report.append(f"已归入  {path.name} → {entry['skill']}/{entry['target']}（{entry['key']}）")
        _register(skill_dir, entry, dry_run)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", type=Path, default=BACKEND.parent, help="where the loose guides are (default: the repository root)")
    parser.add_argument("--skills", type=Path, default=None, help="skills directory (default: SKILLS_DIR or backend/skills)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--replace", action="store_true", help="overwrite a skill's copy that differs from the loose guide")
    args = parser.parse_args()
    report = organize(args.source.resolve(), (args.skills or settings.skills_root()).resolve(), dry_run=args.dry_run, replace=args.replace)
    print("\n".join(report) if report else "没有需要整理的 Markdown 文件")
    return 1 if any(line.startswith(("冲突", "未归类")) for line in report) else 0


if __name__ == "__main__":
    raise SystemExit(main())
