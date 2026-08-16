"""Machine-readable provenance for every reviewed upstream capability source."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator


class UpstreamSourceRecord(BaseModel):
    id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9-]+$")]
    url: Annotated[str, Field(pattern=r"^https://")]
    reviewed_commit: Annotated[str, Field(pattern=r"^[a-f0-9]{40}$")]
    reviewed_at: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
    license_observation: Annotated[str, Field(min_length=2, max_length=500)]
    code_treatment: Literal["attributed-adaptation", "clean-room", "api-interoperability"]
    attribution: Annotated[str, Field(max_length=1000)] = ""
    capability_ids: Annotated[list[str], Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def unique_capability_ids(self) -> "UpstreamSourceRecord":
        if len(self.capability_ids) != len(set(self.capability_ids)):
            raise ValueError(f"duplicate capability IDs for {self.id}")
        return self


def load_upstream_sources() -> list[UpstreamSourceRecord]:
    path = Path(__file__).resolve().parents[1] / "data" / "upstream_sources.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = [UpstreamSourceRecord.model_validate(item) for item in payload]
    ids = [record.id for record in records]
    if len(ids) != len(set(ids)):
        raise RuntimeError("upstream source registry contains duplicate IDs")
    return records


def upstream_source_by_id() -> dict[str, UpstreamSourceRecord]:
    return {record.id: record for record in load_upstream_sources()}
