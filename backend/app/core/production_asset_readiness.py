"""Readiness of a project's five asset kinds before the storyboard stage.

The storyboard agent can only lock people, places, props, costumes and effects
that exist as reference images. This module answers, from the project-scoped
library, whether every asset the screenplay names has one — actors through the
five-view dashboard contract, the other kinds through library reference files.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.character_dashboard import compile_character_dashboard
from app.core.element_scope import element_in_task, element_name_keys, normalized_asset_name
from app.core.production_asset_extractor import extract_production_assets

ASSET_KINDS = ("actor", "scene", "prop", "costume", "effect")
NON_ACTOR_KINDS = ("scene", "prop", "costume", "effect")
KIND_LABELS = {
    "actor": "数字演员",
    "scene": "拍摄场地",
    "prop": "拍摄道具",
    "costume": "服装",
    "effect": "特效",
}
READINESS_KEY = "3_asset_readiness"
_MAX_LISTED = 50


def element_summary(item: Any, owner_id: str, task_id: str) -> dict[str, Any] | None:
    """Ownership-checked, project-scoped summary that never opens file bytes."""
    metadata = getattr(item, "metadata_json", None)
    if (
        str(getattr(item, "owner_id", "") or "") != owner_id
        or not isinstance(metadata, dict)
        or not element_in_task(metadata, task_id)
    ):
        return None
    files = getattr(item, "files", None) or []
    return {
        "id": str(getattr(item, "id", "") or ""),
        "kind": str(getattr(item, "kind", "") or ""),
        "name": str(getattr(item, "name", "") or ""),
        "metadata": dict(metadata),
        "has_image": any(
            str(getattr(file, "mime_type", "") or "").startswith("image/") for file in files
        ),
    }


def expected_asset_names(task: dict, kind: str) -> dict[str, str]:
    """Normalized key -> display name for every asset the screenplay names."""
    expected: dict[str, str] = {}
    for candidate in extract_production_assets(task, kind):
        name = str(candidate.get("name") or "").strip()
        key = normalized_asset_name(name)
        if key and key not in expected:
            expected[key] = name
    return expected


def _actor_readiness(task: dict) -> tuple[bool, int, list[str]]:
    """(ready, total, missing names) from the persisted stage-3 dashboard contract.

    The stage gate already trusts ``assets["3_character_dashboard"]``; reading the
    same record keeps both gates in agreement. Tasks without it are compiled.
    """
    assets = task.get("assets") if isinstance(task.get("assets"), dict) else {}
    persisted = assets.get("3_character_dashboard")
    if isinstance(persisted, dict) and persisted.get("state"):
        characters = [item for item in (persisted.get("characters") or []) if isinstance(item, dict)]
        missing = [
            str(item.get("name") or "").strip()
            for item in characters
            if str(item.get("asset_state") or item.get("assetState") or "") != "READY"
        ]
        return persisted.get("state") == "READY", len(characters), [name for name in missing if name]
    dashboard = compile_character_dashboard(task)
    missing = [character.name for character in dashboard.characters if character.asset_state != "READY"]
    return dashboard.state == "READY", len(dashboard.characters), missing


def evaluate_asset_readiness(
    task: dict,
    summaries: list[dict[str, Any]] | None,
    *,
    library_error: str = "",
) -> dict[str, Any]:
    """Per-kind totals and missing names.

    ``summaries`` is the project-scoped library; ``None`` means the task has no
    library scope (legacy ownerless task) so only the actor contract is enforced.
    """
    cast_ready, cast_total, actor_missing = _actor_readiness(task)
    kinds: dict[str, dict[str, Any]] = {
        "actor": {
            "label": KIND_LABELS["actor"],
            "total": cast_total,
            "ready": cast_total - len(actor_missing),
            "missing": actor_missing[:_MAX_LISTED],
            "enforced": True,
        }
    }
    for kind in NON_ACTOR_KINDS:
        expected = expected_asset_names(task, kind)
        enforced = summaries is not None
        ready_keys: set[str] = set()
        for summary in summaries or []:
            if summary.get("kind") == kind and summary.get("has_image"):
                ready_keys |= element_name_keys(summary.get("name"), summary.get("metadata"))
        missing = [name for key, name in expected.items() if key not in ready_keys] if enforced else []
        kinds[kind] = {
            "label": KIND_LABELS[kind],
            "total": len(expected),
            "ready": len(expected) - len(missing) if enforced else 0,
            "missing": missing[:_MAX_LISTED],
            "enforced": enforced,
        }
    complete = (
        not library_error
        and cast_ready
        and all(not info["missing"] for info in kinds.values())
    )
    return {
        "schema_version": "asset-readiness.v1",
        "complete": complete,
        "library_scoped": summaries is not None,
        "library_error": library_error,
        "kinds": kinds,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


def readiness_reasons(readiness: Any) -> list[str]:
    """Gate messages for a persisted or freshly computed readiness snapshot."""
    if not isinstance(readiness, dict):
        return []
    reasons: list[str] = []
    error = str(readiness.get("library_error") or "").strip()
    if error:
        reasons.append(f"3.资产库读取失败：{error}")
    kinds = readiness.get("kinds") if isinstance(readiness.get("kinds"), dict) else {}
    for kind, info in kinds.items():
        if not isinstance(info, dict) or not info.get("enforced", True):
            continue
        missing = [str(name) for name in (info.get("missing") or []) if str(name).strip()]
        if not missing:
            continue
        label = str(info.get("label") or KIND_LABELS.get(kind, kind))
        shown = "、".join(missing[:5]) + ("…" if len(missing) > 5 else "")
        reasons.append(f"3.{label}缺少参考图（{len(missing)}项）：{shown}")
    if not reasons and readiness.get("complete") is False:
        reasons.append("3.拍摄资产尚未全部生成")
    return reasons
