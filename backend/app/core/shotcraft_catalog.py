"""Typed, non-executing adapter for the Apache-2.0 Video Shotcraft catalog."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator


class ShotcraftCatalogError(ValueError):
    pass


class ShotcraftStats(BaseModel):
    card_count: int
    style_count: int
    preview_count: int
    media_count: int
    newest: str
    sfx_count: int = 149
    sfx_category_count: int = 16


class ShotcraftCard(BaseModel):
    name: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{1,99}$")]
    category: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]{1,39}$")]
    styles: Annotated[list[str], Field(min_length=1, max_length=30)]


class ShotcraftCatalog(BaseModel):
    source: str
    reviewed_commit: str
    library_revision: str
    stats: ShotcraftStats
    categories: dict[str, dict[str, str]]
    cards: list[ShotcraftCard]

    @model_validator(mode="after")
    def validate_counts_and_keys(self) -> "ShotcraftCatalog":
        names = [card.name for card in self.cards]
        styles = [style for card in self.cards for style in card.styles]
        if len(names) != len(set(names)):
            raise ValueError("Shotcraft card names must be unique")
        if len(styles) != len(set(styles)):
            raise ValueError("Shotcraft style keys must be unique")
        if self.stats.card_count != len(self.cards) or self.stats.style_count != len(styles):
            raise ValueError("Shotcraft catalog counts do not match its cards and styles")
        if any(card.category not in self.categories for card in self.cards):
            raise ValueError("Shotcraft card uses an undeclared category")
        return self


class ShotcraftSelectionRequest(BaseModel):
    card: Annotated[str, Field(min_length=2, max_length=100)]
    style: Annotated[str, Field(min_length=2, max_length=100)]
    purpose: Annotated[str, Field(min_length=2, max_length=2000)]
    duration_seconds: Annotated[float, Field(ge=0.5, le=30)]
    asset_ids: Annotated[list[str], Field(max_length=200)] = Field(default_factory=list)


class ShotcraftPlan(BaseModel):
    card: str
    style: str
    category: str
    purpose: str
    duration_seconds: float
    asset_ids: list[str]
    motion_tags: list[str]
    renderer_contract: Literal["canonical-shot-plan-v1"] = "canonical-shot-plan-v1"
    renderer_required: Literal["remotion-compatible"] = "remotion-compatible"
    execution: Literal["not-submitted"] = "not-submitted"


class ShotcraftCatalogLoader:
    EXPECTED_CARDS = 152
    EXPECTED_STYLES = 209
    EXPECTED_PREVIEWS = 209
    MAX_LIBRARY_BYTES = 10 * 1024 * 1024
    _LOCKED_PATH = Path(__file__).resolve().parents[1] / "data" / "video_shotcraft_catalog.json"

    def __init__(self, catalog: ShotcraftCatalog | None = None):
        self.catalog = catalog or self.locked()

    @classmethod
    def _from_normalized(cls, data: dict[str, Any], *, strict: bool) -> ShotcraftCatalog:
        try:
            catalog = ShotcraftCatalog.model_validate(data)
        except Exception as exc:
            raise ShotcraftCatalogError(f"Shotcraft catalog validation failed: {exc}") from exc
        if strict and (
            catalog.stats.card_count != cls.EXPECTED_CARDS
            or catalog.stats.style_count != cls.EXPECTED_STYLES
            or catalog.stats.preview_count != cls.EXPECTED_PREVIEWS
            or catalog.stats.sfx_count != 149
            or catalog.stats.sfx_category_count != 16
        ):
            raise ShotcraftCatalogError("Shotcraft catalog does not match the reviewed capability lock")
        return catalog

    @classmethod
    def locked(cls) -> ShotcraftCatalog:
        if cls._LOCKED_PATH.is_symlink() or cls._LOCKED_PATH.stat().st_size > cls.MAX_LIBRARY_BYTES:
            raise ShotcraftCatalogError("locked Shotcraft catalog file is unsafe")
        try:
            data = json.loads(cls._LOCKED_PATH.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ShotcraftCatalogError("locked Shotcraft catalog cannot be read") from exc
        if not isinstance(data, dict):
            raise ShotcraftCatalogError("locked Shotcraft catalog must be an object")
        stats = data.get("stats", {})
        normalized = {
            **data,
            "stats": {
                "card_count": stats.get("cardCount"),
                "style_count": stats.get("styleCount"),
                "preview_count": stats.get("previewCount"),
                "media_count": stats.get("mediaCount"),
                "newest": stats.get("newest"),
                "sfx_count": stats.get("sfxCount"),
                "sfx_category_count": stats.get("sfxCategoryCount"),
            },
        }
        return cls._from_normalized(normalized, strict=True)

    @classmethod
    def from_checkout(cls, root: str | Path, *, strict: bool = True) -> ShotcraftCatalog:
        checkout = Path(root).expanduser().resolve()
        license_path = checkout / "LICENSE"
        library_path = checkout / "gallery" / "api" / "library.json"
        if (
            not checkout.is_dir()
            or not license_path.is_file()
            or license_path.is_symlink()
            or not library_path.is_file()
            or library_path.is_symlink()
            or not library_path.resolve().is_relative_to(checkout)
        ):
            raise ShotcraftCatalogError("Shotcraft checkout is missing safe LICENSE or library files")
        if license_path.stat().st_size > 100_000 or library_path.stat().st_size > cls.MAX_LIBRARY_BYTES:
            raise ShotcraftCatalogError("Shotcraft checkout metadata exceeds the size limit")
        license_text = license_path.read_text(encoding="utf-8", errors="strict")
        if "Apache License" not in license_text or "Version 2.0" not in license_text:
            raise ShotcraftCatalogError("Shotcraft checkout must retain its Apache-2.0 license")
        try:
            source = json.loads(library_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ShotcraftCatalogError("Shotcraft library JSON is invalid") from exc
        if not isinstance(source, dict) or not isinstance(source.get("cards"), list):
            raise ShotcraftCatalogError("Shotcraft library JSON has an invalid shape")
        stats = source.get("stats", {})
        normalized = {
            "source": "local-apache-checkout",
            "reviewed_commit": "external-checkout",
            "library_revision": str(source.get("revision", "")),
            "stats": {
                "card_count": stats.get("cardCount"),
                "style_count": stats.get("styleCount"),
                "preview_count": stats.get("previewCount"),
                "media_count": stats.get("mediaCount"),
                "newest": stats.get("newest", ""),
                "sfx_count": 149,
                "sfx_category_count": 16,
            },
            "categories": source.get("categories", {}),
            "cards": [
                {
                    "name": card.get("name"),
                    "category": card.get("category"),
                    "styles": [style.get("key") for style in card.get("styles", [])],
                }
                for card in source["cards"]
                if isinstance(card, dict)
            ],
        }
        return cls._from_normalized(normalized, strict=strict)

    def compile_selection(self, request: ShotcraftSelectionRequest) -> ShotcraftPlan:
        card = next((item for item in self.catalog.cards if item.name == request.card), None)
        if not card:
            raise ShotcraftCatalogError(f"unknown Shotcraft card: {request.card}")
        if request.style not in card.styles:
            raise ShotcraftCatalogError(
                f"style {request.style} does not belong to Shotcraft card {request.card}"
            )
        return ShotcraftPlan(
            card=card.name,
            style=request.style,
            category=card.category,
            purpose=request.purpose.strip(),
            duration_seconds=request.duration_seconds,
            asset_ids=list(dict.fromkeys(request.asset_ids)),
            motion_tags=[card.name, request.style],
        )
