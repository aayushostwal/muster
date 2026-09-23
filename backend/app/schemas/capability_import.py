from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


CapabilityKind = Literal["agent", "skill", "mcp"]
SourceRuntime = Literal["claude", "codex"]
ImportStatus = Literal["new", "updated", "unchanged"]


class CapabilityImportPreview(BaseModel):
    candidate_id: str
    resource_type: CapabilityKind
    source_runtime: SourceRuntime
    source_scope: str
    source_locator: str
    name: str
    target_name: str
    description: str | None = None
    status: ImportStatus
    preview: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class CapabilityDiscoveryResponse(BaseModel):
    items: list[CapabilityImportPreview]
    warnings: list[str] = Field(default_factory=list)


class CapabilityImportRequest(BaseModel):
    candidate_ids: list[str] = Field(min_length=1, max_length=250)


class CapabilityImportResultItem(BaseModel):
    import_id: uuid.UUID
    resource_type: CapabilityKind
    resource_id: uuid.UUID
    name: str
    action: Literal["created", "updated", "unchanged"]


class CapabilityImportResponse(BaseModel):
    items: list[CapabilityImportResultItem]


class CapabilityImportRead(BaseModel):
    id: uuid.UUID
    resource_type: CapabilityKind
    resource_id: uuid.UUID
    source_runtime: SourceRuntime
    source_scope: str
    source_locator: str
    source_checksum: str
    source_metadata: dict[str, Any]
    synced_at: datetime
