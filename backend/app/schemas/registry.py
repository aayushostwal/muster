from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models import AgentBackend
from app.schemas.mcp_server import McpConfig
from app.schemas.tool import ToolRuleConfig


class DirectoryResourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    path: str = Field(min_length=1, max_length=1000)
    description: str | None = None

    @field_validator("path")
    @classmethod
    def absolute_path(cls, value: str) -> str:
        if not value.startswith("/"):
            raise ValueError("Directory path must be absolute")
        return value


class DirectoryResourceUpdate(BaseModel):
    name: str | None = None
    path: str | None = None
    description: str | None = None

    @field_validator("path")
    @classmethod
    def absolute_path(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith("/"):
            raise ValueError("Directory path must be absolute")
        return value


class DirectoryResourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    path: str
    description: str | None
    created_at: datetime
    updated_at: datetime


class GlobalMcpCreate(BaseModel):
    name: str
    description: str | None = None
    config: McpConfig
    enabled: bool = True


class GlobalMcpUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    config: McpConfig | None = None
    enabled: bool | None = None


class GlobalMcpRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    description: str | None
    config: dict
    enabled: bool
    created_at: datetime
    updated_at: datetime


class AgentProfileCreate(BaseModel):
    name: str
    description: str | None = None
    system_prompt: str
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class AgentProfileUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    system_prompt: str | None = None
    config: dict[str, Any] | None = None
    enabled: bool | None = None


class AgentProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    description: str | None
    system_prompt: str
    config: dict
    enabled: bool
    created_at: datetime
    updated_at: datetime


class SkillTagsMixin(BaseModel):
    tags: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for value in values:
            clean = " ".join(value.strip().split())
            if not clean:
                continue
            if len(clean) > 32:
                raise ValueError("Skill tags must be 32 characters or fewer")
            key = clean.casefold()
            if key not in seen:
                normalized.append(clean)
                seen.add(key)
        return normalized


class SkillCreate(SkillTagsMixin):
    name: str
    description: str | None = None
    instructions: str
    enabled: bool = True


class SkillUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    instructions: str | None = None
    tags: list[str] | None = Field(default=None, max_length=12)
    enabled: bool | None = None

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        return SkillTagsMixin(tags=values).tags


class SkillRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    description: str | None
    instructions: str
    tags: list[str]
    enabled: bool
    created_at: datetime
    updated_at: datetime


class GlobalToolCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    config: ToolRuleConfig
    enabled: bool = True


class GlobalToolUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    config: ToolRuleConfig | None = None
    enabled: bool | None = None


class GlobalToolRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    description: str | None
    config: dict
    enabled: bool
    created_at: datetime
    updated_at: datetime


class CapabilityOverridePut(BaseModel):
    enabled: bool = True
    config_override: dict[str, Any] = Field(default_factory=dict)


class CapabilityRead(BaseModel):
    resource_type: str
    resource_id: uuid.UUID
    name: str
    description: str | None
    enabled: bool
    global_enabled: bool
    config: dict[str, Any]


class ModelOption(BaseModel):
    id: str
    label: str
    backend: AgentBackend
    source: str


class ModelCatalog(BaseModel):
    backend: AgentBackend
    items: list[ModelOption]
    refreshed_at: datetime
    expires_at: datetime
    cached: bool
    discovery_error: str | None = None
