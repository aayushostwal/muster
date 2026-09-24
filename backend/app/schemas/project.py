"""Pydantic schemas for Project."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.db.models import AgentBackend, PrPolicy


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None
    default_backend: AgentBackend
    default_model: str | None = None
    default_context_strategy: str = "full"
    primary_directory_id: uuid.UUID | None = None
    pr_policy: PrPolicy = PrPolicy.preferred
    pr_provider: str = "github"
    pr_remote_name: str = "origin"
    pr_branch_prefix: str = "muster/"
    pr_base_branch: str | None = None
    pr_validation_command: str | None = None
    pr_draft_default: bool = False


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    default_backend: AgentBackend | None = None
    default_model: str | None = None
    default_context_strategy: str | None = None
    primary_directory_id: uuid.UUID | None = None
    pr_policy: PrPolicy | None = None
    pr_provider: str | None = None
    pr_remote_name: str | None = None
    pr_branch_prefix: str | None = None
    pr_base_branch: str | None = None
    pr_validation_command: str | None = None
    pr_draft_default: bool | None = None


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    default_backend: AgentBackend
    default_model: str | None
    default_context_strategy: str
    primary_directory_id: uuid.UUID | None
    pr_policy: PrPolicy
    pr_provider: str
    pr_remote_name: str
    pr_branch_prefix: str
    pr_base_branch: str | None
    pr_validation_command: str | None
    pr_draft_default: bool
    created_at: datetime
    updated_at: datetime
