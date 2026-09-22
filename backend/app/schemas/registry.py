from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.models import AgentBackend
from app.schemas.mcp_server import McpConfig


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
    backend: AgentBackend
    system_prompt: str
    model: str | None = None
    thinking_level: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class AgentProfileUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    backend: AgentBackend | None = None
    system_prompt: str | None = None
    model: str | None = None
    thinking_level: Literal["low", "medium", "high", "xhigh", "max"] | None = None
    config: dict[str, Any] | None = None
    enabled: bool | None = None


class AgentProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    description: str | None
    backend: AgentBackend
    system_prompt: str
    model: str | None
    thinking_level: str
    config: dict
    enabled: bool
    created_at: datetime
    updated_at: datetime


class SkillCreate(BaseModel):
    name: str
    description: str | None = None
    instructions: str
    enabled: bool = True


class SkillUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    instructions: str | None = None
    enabled: bool | None = None


class SkillRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    description: str | None
    instructions: str
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
