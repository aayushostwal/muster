"""Pydantic schemas for CronJob."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.db.models import AgentBackend


class RunWindow(BaseModel):
    timezone: str = "Asia/Kolkata"
    window_start: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    window_end: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        if value is None:
            raise ValueError("Choose a timezone")
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Choose a valid IANA timezone") from exc
        return value

    @model_validator(mode="after")
    def complete_window(self):
        if (self.window_start is None) != (self.window_end is None):
            raise ValueError("Set both window start and end, or clear both")
        if self.window_start is not None and self.window_start == self.window_end:
            raise ValueError("Window start and end must differ")
        return self


class CronJobCreate(RunWindow):
    name: str
    schedule_expr: str = "0 * * * *"
    interval_minutes: int | None = Field(default=None, ge=1, le=525600)
    prompt: str
    backend: AgentBackend
    model: str | None = None
    thinking_level: Literal["low", "medium", "high", "xhigh", "max"] = "medium"


class CronJobUpdate(BaseModel):
    timezone: str | None = None
    window_start: str | None = None
    window_end: str | None = None
    name: str | None = None
    schedule_expr: str | None = None
    interval_minutes: int | None = Field(default=None, ge=1, le=525600)
    prompt: str | None = None
    backend: AgentBackend | None = None
    model: str | None = None
    thinking_level: Literal["low", "medium", "high", "xhigh", "max"] | None = None


class CronJobRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    schedule_expr: str
    interval_minutes: int | None
    timezone: str
    window_start: str | None
    window_end: str | None
    prompt: str
    backend: AgentBackend
    model: str | None
    thinking_level: str
    enabled: bool
    last_run_at: datetime | None
    last_status: str | None
    created_at: datetime
