"""Pydantic schemas for the PR delivery workflow (see docs/SPEC.md "PR delivery")."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import PrDeliveryStatus, PrPolicy


class PrDeliveryEligibility(BaseModel):
    """Read-only snapshot of whether/why a task can raise a PR right now.

    Computed live from `git`/the filesystem on every call -- never cached,
    never inferred from agent text.
    """

    policy: PrPolicy
    is_git_repo: bool
    has_remote: bool
    remote_name: str
    remote_url: str | None
    current_branch: str | None
    detached_head: bool
    is_protected_branch: bool
    baseline_captured: bool
    dirty_paths: list[str] = Field(default_factory=list)
    eligible_paths: list[str] = Field(default_factory=list)
    excluded_paths: list[str] = Field(default_factory=list)
    eligible: bool
    reason: str | None = None
    active_run: "PrDeliveryRunRead | None" = None


class PrDeliveryPrepareRequest(BaseModel):
    """Optional overrides accepted from the "Prepare PR" action / `/pr`."""

    base_branch: str | None = None
    remote_name: str | None = None
    draft: bool | None = None


class PrDeliveryConfirmRequest(BaseModel):
    """User-editable fields shown on the pre-mutation confirmation card."""

    commit_message: str | None = None
    pr_title: str | None = None
    pr_body: str | None = None
    draft: bool | None = None


class PrDeliveryCompleteWithoutPr(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class PrDeliveryRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    project_id: uuid.UUID
    status: PrDeliveryStatus
    provider: str
    repository: str | None
    remote_name: str
    head_branch: str | None
    base_branch: str | None
    draft: bool
    file_paths: list[str]
    excluded_paths: list[str]
    commit_message: str | None
    pr_title: str | None
    pr_body: str | None
    validation_command: str | None
    validation_output: str | None
    pr_url: str | None
    pr_number: int | None
    pr_state: str | None
    error_message: str | None
    completion_reason: str | None
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None


PrDeliveryEligibility.model_rebuild()
