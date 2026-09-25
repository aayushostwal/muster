"""Dispatch task lifecycle operations to structured or interactive runtimes."""
from __future__ import annotations

import uuid
from typing import Any

from app.config import settings
from app.db.models import AgentBackend, RuntimeMode, Task
from app.db.session import SessionLocal


class RuntimeManager:
    def __init__(self, structured: Any, terminal: Any) -> None:
        self.structured = structured
        self.terminal = terminal

    async def _mode(self, task_id: uuid.UUID) -> RuntimeMode:
        async with SessionLocal() as db:
            task = await db.get(Task, task_id)
            if task is None:
                return RuntimeMode.structured
            value = task.runtime_mode
            return value if isinstance(value, RuntimeMode) else RuntimeMode(value)

    async def _manager(self, task_id: uuid.UUID, *, require_enabled: bool = False) -> Any:
        if await self._mode(task_id) == RuntimeMode.interactive:
            if require_enabled and not settings.interactive_terminal_enabled:
                raise RuntimeError("Interactive terminal runtime is disabled")
            return self.terminal
        return self.structured

    async def trigger(self, task_id: uuid.UUID) -> None:
        await (await self._manager(task_id, require_enabled=True)).trigger(task_id)

    async def resume(self, task_id: uuid.UUID) -> None:
        await (await self._manager(task_id, require_enabled=True)).resume(task_id)

    async def cancel(self, task_id: uuid.UUID) -> None:
        await (await self._manager(task_id)).cancel(task_id)

    async def complete(self, task_id: uuid.UUID) -> None:
        await (await self._manager(task_id)).complete(task_id)

    async def retry_now(self, task_id: uuid.UUID) -> None:
        await (await self._manager(task_id, require_enabled=True)).retry_now(task_id)

    async def restart_from_beginning(self, task_id: uuid.UUID) -> None:
        await (await self._manager(task_id, require_enabled=True)).restart_from_beginning(task_id)

    async def switch_backend(self, task_id: uuid.UUID, backend: AgentBackend) -> None:
        await (await self._manager(task_id, require_enabled=True)).switch_backend(task_id, backend)

    async def resume_after_approval(self, task_id: uuid.UUID) -> None:
        # Native terminal sessions answer approvals inside the CLI. Persisted
        # Muster approval requests are produced only by the structured runner.
        await self.structured.resume_after_approval(task_id)

    async def reconcile_interrupted_tasks(self) -> int:
        return await self.structured.reconcile_interrupted_tasks()

    async def shutdown(self) -> None:
        await self.terminal.shutdown()
        await self.structured.shutdown()

    def __getattr__(self, name: str) -> Any:
        # Keep existing internal diagnostics/tests available while the public
        # lifecycle surface is routed by runtime mode.
        return getattr(self.structured, name)
