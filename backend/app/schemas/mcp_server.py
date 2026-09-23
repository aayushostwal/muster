"""Pydantic schemas for McpBinding."""
from __future__ import annotations

import uuid
from datetime import datetime

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class McpConfig(BaseModel):
    """Portable MCP configuration shared by the Claude and Codex adapters."""

    transport: Literal["stdio", "http", "sse"] = "stdio"
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    bearer_token_env_var: str | None = None

    @model_validator(mode="after")
    def validate_transport(self):
        if self.transport == "stdio" and not self.command:
            raise ValueError("stdio MCP servers require a command")
        if self.transport in {"http", "sse"} and not self.url:
            raise ValueError("remote MCP servers require a URL")
        return self


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
