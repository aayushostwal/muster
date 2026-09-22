"""Pydantic schemas for McpBinding."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class McpConfig(BaseModel):
    """Minimal schema an MCP server config must satisfy."""

    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)


class McpBindingCreate(BaseModel):
    name: str
    config: McpConfig


class McpBindingUpdate(BaseModel):
    name: str | None = None
    config: McpConfig | None = None


class McpBindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    config: dict
    created_at: datetime
