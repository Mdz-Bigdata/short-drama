#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""List the props, vehicles and products whose real size the scale tables cannot find.

Reads every project's stage-2 breakdown (props / vehicles / products) and the element library
(kinds prop / vehicle / product), read-only. A name is listed when ``prop_scale.lookup`` finds
nothing and no size was given by hand or written in its description; those are drawn and
prompted at a category estimate (``prop_turnaround.plan_prop``). Add them to
``app/data/props/everyday_items.json`` (the official table ``scale_reference.json`` is not edited).

    .venv/bin/python scripts/missing_prop_sizes.py            # a Markdown table
    .venv/bin/python scripts/missing_prop_sizes.py --json     # the same rows as JSON
"""

from __future__ import annotations

import argparse
import asyncio
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env", override=False)

from sqlalchemy import select  # noqa: E402

from app import settings  # noqa: E402
from app.core import prop_scale  # noqa: E402
from app.core.prop_turnaround import plan_prop  # noqa: E402
from app.platform.models import ElementAsset  # noqa: E402
from app.platform.store import PlatformStore  # noqa: E402
from app.repository.task_repo import TaskRepository  # noqa: E402

_CATALOG_KINDS = {"props": "prop", "vehicles": "vehicle", "products": "product"}
_LIBRARY_KINDS = ("prop", "vehicle", "product")


def _from_projects() -> list[tuple[str, str, str, str]]:
    """(name, kind, description, project) from every project's stage-2 breakdown."""
    repo = TaskRepository()
    rows = []
    for summary in repo.list_all_tasks():
        task_id = str((summary or {}).get("task_id") or "")
        task = summary if "assets" in (summary or {}) else repo.get_task(task_id)
        catalog = (((task or {}).get("assets") or {}).get("2_breakdown") or {}).get("production_assets") or {}
        for key, kind in _CATALOG_KINDS.items():
            for item in catalog.get(key) or []:
                if isinstance(item, dict) and str(item.get("name") or "").strip():
                    rows.append((str(item["name"]).strip(), kind, str(item.get("description") or ""), task_id[:8]))
    return rows


async def _from_library() -> list[tuple[str, str, str, str]]:
    """(name, kind, description, project) from the element library; elements sized by hand are left out."""
    store = PlatformStore(settings.database_url())
    try:
        async with store.sessions() as session:
            found = (await session.execute(select(ElementAsset).where(ElementAsset.kind.in_(_LIBRARY_KINDS)))).scalars().all()
    finally:
        await store.engine.dispose()
    rows = []
    for item in found:
        metadata = item.metadata_json or {}
        if metadata.get("prop_length_cm"):
            continue
        rows.append((str(item.name).strip(), str(item.kind), str(item.description or ""), str(metadata.get("task_id") or "")[:8]))
    return rows


def missing() -> list[dict]:
    seen: dict[str, dict] = {}
    counts: collections.Counter[str] = collections.Counter()
    for name, kind, description, project in [*_from_projects(), *asyncio.run(_from_library())]:
        if not name or prop_scale.lookup(name) is not None:
            continue
        plan = plan_prop(name, description)
        if plan.size_source == "description":
            continue
        counts[name] += 1
        row = seen.setdefault(name, {"name": name, "kinds": set(), "projects": set(), "estimate_cm": plan.longest_cm, "description": ""})
        row["kinds"].add(kind)
        if project:
            row["projects"].add(project)
        row["description"] = row["description"] or description.strip()[:60]
    rows = sorted(seen.values(), key=lambda row: (-counts[row["name"]], row["name"]))
    return [{**row, "count": counts[row["name"]], "kinds": sorted(row["kinds"]), "projects": sorted(row["projects"])} for row in rows]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="print JSON instead of a Markdown table")
    rows = missing()
    if parser.parse_args().json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return
    if not rows:
        print("All props, vehicles and products have a size in the tables.")
        return
    print(f"{len(rows)} names have no size in the tables (drawn and prompted at a category estimate):\n")
    print("| name | kind | times | projects | estimate now | description |")
    print("|---|---|---|---|---|---|")
    for row in rows:
        print(f"| {row['name']} | {'/'.join(row['kinds'])} | {row['count']} | {' '.join(row['projects'])} | "
              f"{row['estimate_cm']:g} cm | {row['description']} |")


if __name__ == "__main__":
    main()
