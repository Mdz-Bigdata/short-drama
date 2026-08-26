"""Pure compiler for the Character Designer dashboard contract.

The compiler intentionally performs no I/O.  It only normalizes persisted Stage 3
assets so GET requests can safely support both current and legacy tasks.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from typing import Any
from urllib.parse import urlsplit

from app.schema.character_dashboard import (
    FIVE_VIEW_ORDER,
    CharacterColor,
    CharacterDashboardCharacter,
    CharacterDashboardResponse,
    CharacterDashboardStats,
    CharacterDesignState,
    CharacterFiveViewQuality,
    CharacterProjectProfile,
    CharacterQualityIssue,
    CharacterRisk,
    CharacterStateAnchor,
    CharacterViewAsset,
    CharacterViewContract,
)


_VIEW_ALIASES = {
    "front": "front",
    "frontview": "front",
    "正面": "front",
    "0": "front",
    "0°": "front",
    "frontthreequarter": "front_three_quarter",
    "frontthreequarterview": "front_three_quarter",
    "front3quarter": "front_three_quarter",
    "正面四分之三": "front_three_quarter",
    "正面四分之三视图": "front_three_quarter",
    "45": "front_three_quarter",
    "45°": "front_three_quarter",
    "profile": "profile",
    "profileview": "profile",
    "standardprofile": "profile",
    "standardprofileview": "profile",
    "side": "profile",
    "sideview": "profile",
    "侧面": "profile",
    "标准侧面": "profile",
    "标准侧面视图": "profile",
    "90": "profile",
    "90°": "profile",
    "rearthreequarter": "rear_three_quarter",
    "rearthreequarterview": "rear_three_quarter",
    "backthreequarter": "rear_three_quarter",
    "背面四分之三": "rear_three_quarter",
    "背面四分之三视图": "rear_three_quarter",
    "135": "rear_three_quarter",
    "135°": "rear_three_quarter",
    "back": "back",
    "backview": "back",
    "rear": "back",
    "rearview": "back",
    "背面": "back",
    "180": "back",
    "180°": "back",
}
_ROLE_HEADER = re.compile(
    r"(?m)^[ \t]{0,3}(?:#{1,6}[ \t]+|\*\*)"
    r"(?:\d{1,3}[.、][ \t]*)?"
    r"(?:核心角色|主角|男主|女主|对手角色|反派对手|大反派|反派|男配角|女配角|男配|女配|配角|角色)"
    r"[ \t]*(?:[（(][^：:）)\n]{1,12}[）)])?[ \t]*"
    r"[:：][ \t]*(?P<name>[\u3400-\u9fff][\u3400-\u9fff·]{1,7})"
    r"(?:\*\*)?[ \t]*(?:$|[（(])"
)
_NON_CHARACTER_NAMES = {
    "角色方案", "角色设计", "角色设定", "角色清单", "人物关系", "项目基准",
    "风险清单", "五视图", "声音设定", "色彩设定", "身份设定", "角色档案",
    "总表", "角色总表", "角色UID总表", "主角", "反派", "配角",
}


def _text(value: Any, limit: int, *, multiline: bool = False) -> str:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return ""
    text = unicodedata.normalize("NFKC", str(value)).replace("\x00", "")
    text = "".join(char for char in text if char in "\n\t" or ord(char) >= 32)
    if multiline:
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
    else:
        text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _safe_media_url(value: Any) -> str | None:
    text = _text(value, 4000)
    if not text or "\\" in text:
        return None
    try:
        parsed = urlsplit(text)
    except ValueError:
        return None
    if not parsed.scheme and not parsed.netloc:
        segments = [segment for segment in parsed.path.split("/") if segment]
        if parsed.path.startswith("/media/") and ".." not in segments:
            return text
        return None
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return None
    if parsed.username or parsed.password:
        return None
    return text


def _canonical_view_key(value: Any) -> str | None:
    text = _text(value, 80).lower().replace("-", "").replace("_", "").replace(" ", "")
    return _VIEW_ALIASES.get(text)


def _stable_character_id(name: str) -> str:
    digest = hashlib.sha256(name.casefold().encode("utf-8")).hexdigest()[:16]
    return f"character-{digest}"


def _stable_state_id(character_name: str, value: Any, title: str) -> str:
    supplied = re.sub(r"[^A-Za-z0-9_.:-]+", "-", _text(value, 120)).strip("-.")
    if supplied:
        return supplied[:120]
    digest = hashlib.sha256(f"{character_name}|{title}".encode("utf-8")).hexdigest()[:12]
    return f"state-{digest}"


def _canonical_hash_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= 12:
        return "<max-depth>"
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, dict):
        return {
            str(key): _canonical_hash_value(item, depth=depth + 1)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_hash_value(item, depth=depth + 1) for item in value]
    return f"<{type(value).__module__}.{type(value).__qualname__}>"


def _source_hash(assets: dict[str, Any]) -> str:
    relevant = {
        "3": assets.get("3"),
        "3_raw": assets.get("3_raw"),
        "3_characters": assets.get("3_characters"),
        "3_sheets": assets.get("3_sheets"),
        "3_dna": assets.get("3_dna"),
    }
    encoded = json.dumps(
        _canonical_hash_value(relevant),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _raw_character_blocks(raw_text: str) -> list[tuple[str, str]]:
    matches = list(_ROLE_HEADER.finditer(raw_text))
    blocks: list[tuple[str, str]] = []
    for index, match in enumerate(matches[:500]):
        name = _text(match.group("name").strip("·"), 80)
        if not name or name in _NON_CHARACTER_NAMES:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(raw_text)
        description = _text(raw_text[match.end():end], 4000, multiline=True)
        blocks.append((name, description))
    return blocks


def _structured_characters(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value[:500] if isinstance(item, dict)]
    if not isinstance(value, dict):
        return []
    result: list[dict[str, Any]] = []
    for name, item in list(value.items())[:500]:
        if isinstance(item, dict):
            result.append({"name": name, **item})
        else:
            result.append({"name": name, "desc": item})
    return result


def _dna_characters(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value[:500] if isinstance(item, dict)]
    if isinstance(value, dict):
        return [
            {"name": name, **item} if isinstance(item, dict) else {"name": name, "identity": item}
            for name, item in list(value.items())[:500]
        ]
    return []


def _sheet_entries(value: Any) -> list[tuple[str, Any]]:
    if not isinstance(value, dict):
        return []
    return sorted(
        ((_text(name, 80), item) for name, item in list(value.items())[:500]),
        key=lambda pair: pair[0].casefold(),
    )


def _normalize_project(value: Any) -> CharacterProjectProfile:
    item = value if isinstance(value, dict) else {}
    return CharacterProjectProfile(
        genre=_text(item.get("genre"), 160),
        platform=_text(item.get("platform"), 300),
        delivery_spec=_text(item.get("delivery_spec", item.get("deliverySpec")), 300),
        constraints=_text(item.get("constraints"), 2000, multiline=True),
    )


def _normalize_risks(value: Any) -> list[CharacterRisk]:
    if not isinstance(value, list):
        return []
    risks: list[CharacterRisk] = []
    for item in value[:100]:
        if not isinstance(item, dict):
            continue
        title = _text(item.get("item"), 300)
        if not title:
            continue
        status = _text(item.get("status"), 20).upper()
        risks.append(CharacterRisk(
            item=title,
            status=status if status in {"BLOCKED", "PENDING", "PASS"} else "PENDING",
            note=_text(item.get("note"), 2000, multiline=True),
        ))
    return risks


def _normalize_colors(value: Any) -> list[CharacterColor]:
    if not isinstance(value, list):
        return []
    colors: list[CharacterColor] = []
    seen: set[tuple[str, str | None]] = set()
    for item in value[:20]:
        if not isinstance(item, dict):
            continue
        name = _text(item.get("name"), 80)
        raw_hex = _text(item.get("hex"), 20)
        hex_value = raw_hex.upper() if re.fullmatch(r"#[0-9A-Fa-f]{6}", raw_hex) else None
        if not name and not hex_value:
            continue
        key = (name.casefold(), hex_value)
        if key in seen:
            continue
        seen.add(key)
        colors.append(CharacterColor(name=name, hex=hex_value))
    return colors


def _normalize_anchors(value: Any) -> list[CharacterStateAnchor]:
    by_view: dict[str, str] = {}
    if isinstance(value, list):
        for item in value[:50]:
            if not isinstance(item, dict):
                continue
            key = _canonical_view_key(item.get("view"))
            if key and key not in by_view:
                by_view[key] = _text(item.get("detail"), 1000, multiline=True)
    return [CharacterStateAnchor(view=key, detail=by_view.get(key, "")) for key in FIVE_VIEW_ORDER]


def _normalize_states(character_name: str, value: Any) -> list[CharacterDesignState]:
    if not isinstance(value, list):
        return []
    states: list[CharacterDesignState] = []
    seen: set[str] = set()
    for item in value[:50]:
        if not isinstance(item, dict):
            continue
        title = _text(item.get("title"), 200) or "默认造型状态"
        state_id = _stable_state_id(character_name, item.get("state_id", item.get("stateId")), title)
        if state_id in seen:
            continue
        seen.add(state_id)
        states.append(CharacterDesignState(
            state_id=state_id,
            title=title,
            dna=_text(item.get("dna"), 4000, multiline=True),
            hair=_text(item.get("hair"), 1000, multiline=True),
            body=_text(item.get("body"), 1000, multiline=True),
            clothing=_text(item.get("clothing"), 2000, multiline=True),
            accessories=_text(item.get("accessories"), 1000, multiline=True),
            style=_text(item.get("style"), 1000, multiline=True),
            anchors=_normalize_anchors(item.get("anchors")),
        ))
    return states


def _normalize_views(value: Any) -> list[CharacterViewAsset]:
    urls: dict[str, str] = {}
    if isinstance(value, dict):
        iterable: list[Any] = [
            {"view": key, "image_url": item} if not isinstance(item, dict) else {"view": key, **item}
            for key, item in list(value.items())[:50]
        ]
    elif isinstance(value, list):
        iterable = value[:50]
    else:
        iterable = []
    for position, item in enumerate(iterable):
        if isinstance(item, str):
            key = FIVE_VIEW_ORDER[position] if position < 5 else None
            url = _safe_media_url(item)
        elif isinstance(item, dict):
            key = _canonical_view_key(item.get("view", item.get("key")))
            if not key and position < 5:
                key = FIVE_VIEW_ORDER[position]
            url = _safe_media_url(item.get("image_url", item.get("imageUrl", item.get("url"))))
        else:
            continue
        if key and url and key not in urls:
            urls[key] = url
    return [
        CharacterViewAsset(key=key, order=index, image_url=urls.get(key), available=key in urls)
        for index, key in enumerate(FIVE_VIEW_ORDER, start=1)
    ]


def _finite_float(value: Any, *, minimum: float, maximum: float) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed if math.isfinite(parsed) and minimum <= parsed <= maximum else None


def _normalize_quality(value: Any) -> CharacterFiveViewQuality:
    item = value if isinstance(value, dict) else {}
    raw_passed = item.get("passed")
    passed = raw_passed if isinstance(raw_passed, bool) else None
    palette = _finite_float(item.get("palette_similarity", item.get("paletteSimilarity")), minimum=0, maximum=1)
    hashes_value = item.get("unique_view_hashes", item.get("uniqueViewHashes"))
    hashes = hashes_value if isinstance(hashes_value, int) and not isinstance(hashes_value, bool) and 0 <= hashes_value <= 5 else None
    entropy: list[float] = []
    raw_entropy = item.get("entropy")
    if isinstance(raw_entropy, list):
        for entry in raw_entropy[:5]:
            parsed = _finite_float(entry, minimum=0, maximum=100)
            if parsed is not None:
                entropy.append(parsed)
    issues: list[CharacterQualityIssue] = []
    raw_issues = item.get("issues")
    if isinstance(raw_issues, list):
        for issue in raw_issues[:50]:
            if not isinstance(issue, dict):
                continue
            raw_index = issue.get("view_index", issue.get("viewIndex"))
            view_index = raw_index if isinstance(raw_index, int) and not isinstance(raw_index, bool) and 1 <= raw_index <= 5 else None
            issues.append(CharacterQualityIssue(
                code=_text(issue.get("code"), 120) or "quality_issue",
                message=_text(issue.get("message"), 1000, multiline=True),
                view_index=view_index,
            ))
    return CharacterFiveViewQuality(
        passed=passed,
        palette_similarity=palette,
        unique_view_hashes=hashes,
        entropy=entropy,
        issues=issues,
    )


def _asset_state(views: list[CharacterViewAsset], sheet_url: str | None, quality: CharacterFiveViewQuality) -> str:
    available = sum(view.available for view in views)
    if quality.passed is False:
        return "FAILED"
    if available == 5:
        return "READY" if quality.passed is True else "NEEDS_REVIEW"
    if available:
        return "PARTIAL"
    if sheet_url:
        return "NEEDS_REVIEW"
    return "MISSING"


def _view_contract() -> CharacterViewContract:
    return CharacterViewContract()


def compile_character_dashboard(task: dict[str, Any]) -> CharacterDashboardResponse:
    """Normalize Stage 3 assets without network access, filesystem access, or writes."""
    config = task.get("config") if isinstance(task.get("config"), dict) else {}
    assets = task.get("assets") if isinstance(task.get("assets"), dict) else {}
    raw_text = _text(assets.get("3") or assets.get("3_raw"), 2_000_000, multiline=True)
    dna = assets.get("3_dna") if isinstance(assets.get("3_dna"), dict) else {}

    records: dict[str, dict[str, Any]] = {}

    def ensure(name_value: Any) -> dict[str, Any] | None:
        name = _text(name_value, 80)
        if not name:
            return None
        normalized = name.casefold()
        if normalized not in records:
            records[normalized] = {"name": name}
        return records[normalized]

    for item in _structured_characters(assets.get("3_characters")):
        record = ensure(item.get("name"))
        if record is not None and "character" not in record:
            record["character"] = item

    for item in _dna_characters(dna.get("characters")):
        record = ensure(item.get("name"))
        if record is not None and "dna" not in record:
            record["dna"] = item

    for name, item in _sheet_entries(assets.get("3_sheets")):
        record = ensure(name)
        if record is not None and "sheet" not in record:
            if isinstance(item, dict):
                record["sheet"] = item.get("sheet", item.get("sheet_url", item.get("sheetUrl", item.get("url"))))
            else:
                record["sheet"] = item

    # Raw Markdown is a compatibility fallback, not an authoritative roster.  If
    # structured Stage 3 assets already identify characters, raw text may enrich
    # only those exact names; it must never introduce metadata headings as people.
    for name, description in _raw_character_blocks(raw_text):
        record = records.get(name.casefold()) if records else ensure(name)
        if record is not None and not record.get("raw_description"):
            record["raw_description"] = description

    characters: list[CharacterDashboardCharacter] = []
    for record in records.values():
        character = record.get("character") if isinstance(record.get("character"), dict) else {}
        dna_character = record.get("dna") if isinstance(record.get("dna"), dict) else {}
        name = record["name"]
        states = _normalize_states(name, dna_character.get("states"))
        description = (
            _text(character.get("desc", character.get("description")), 4000, multiline=True)
            or (states[0].dna if states else "")
            or _text(dna_character.get("identity"), 4000, multiline=True)
            or _text(record.get("raw_description"), 4000, multiline=True)
        )
        sheet_url = _safe_media_url(
            character.get("sheet", character.get("sheet_url", character.get("sheetUrl")))
        ) or _safe_media_url(record.get("sheet"))
        views = _normalize_views(character.get("views"))
        quality = _normalize_quality(
            character.get("five_view_quality", character.get("fiveViewQuality", character.get("quality")))
        )
        characters.append(CharacterDashboardCharacter(
            character_id=_stable_character_id(name),
            name=name,
            role=_text(character.get("role"), 120) or "剧情角色",
            description=description,
            identity=_text(dna_character.get("identity"), 1000, multiline=True),
            voice_id=_text(dna_character.get("voice_id", dna_character.get("voiceId")), 160),
            colors=_normalize_colors(dna_character.get("colors")),
            states=states,
            sheet_url=sheet_url,
            asset_state=_asset_state(views, sheet_url, quality),
            views=views,
            quality=quality,
        ))

    state_counts = {
        state: sum(character.asset_state == state for character in characters)
        for state in ("READY", "NEEDS_REVIEW", "PARTIAL", "MISSING", "FAILED")
    }
    available_views = sum(view.available for character in characters for view in character.views)
    stats = CharacterDashboardStats(
        character_count=len(characters),
        ready_count=state_counts["READY"],
        needs_review_count=state_counts["NEEDS_REVIEW"],
        partial_count=state_counts["PARTIAL"],
        missing_count=state_counts["MISSING"],
        failed_count=state_counts["FAILED"],
        available_view_count=available_views,
        expected_view_count=len(characters) * 5,
    )
    assumptions = []
    raw_assumptions = dna.get("assumptions")
    if isinstance(raw_assumptions, list):
        assumptions = [
            text for text in (_text(item, 1000, multiline=True) for item in raw_assumptions[:100]) if text
        ]
    has_stage_three_source = any(
        bool(assets.get(key))
        for key in ("3", "3_raw", "3_characters", "3_sheets", "3_dna")
    )
    dashboard_state = (
        "READY" if characters and all(character.asset_state == "READY" for character in characters)
        else "INCOMPLETE" if has_stage_three_source
        else "WAITING"
    )
    return CharacterDashboardResponse(
        task_id=_text(task.get("task_id"), 120) or "unknown-task",
        source_hash=_source_hash(assets),
        title=_text(config.get("title_suggestion"), 500) or "未命名短剧",
        state=dashboard_state,
        view_contract=_view_contract(),
        stats=stats,
        project=_normalize_project(dna.get("project")),
        assumptions=assumptions,
        risks=_normalize_risks(dna.get("risks")),
        characters=characters,
        raw_text=raw_text,
    )
