"""Pydantic schemas for ToolBinding."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ToolRuleConfig(BaseModel):
    backend: Literal["all", "claude_code", "codex"] = "all"
    decision: Literal["allow", "deny"] = "allow"
    claude_pattern: str | None = None
    codex_prefix: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_runtime_rules(self):
        if self.backend in {"all", "claude_code"} and not (self.claude_pattern or "").strip():
            raise ValueError("A Claude tool pattern is required")
        if self.backend in {"all", "codex"} and not self.codex_prefix:
            raise ValueError("A Codex command prefix is required")
        return self


class ToolBindingCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    config: ToolRuleConfig


class ToolBindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    config: dict
    created_at: datetime


class ToolApprovalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    invocation_id: uuid.UUID | None
    backend: str
    tool_name: str
    tool_input: dict
    permission_rule: dict
    reason: str | None
    status: str
    resolution_scope: str | None
    created_at: datetime
    resolved_at: datetime | None


class ToolApprovalResolve(BaseModel):
    decision: Literal["approve_once", "always_allow", "deny"]
