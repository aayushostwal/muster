"""Local stdio MCP server for creating and operating Muster tasks.

The MCP process deliberately talks to the running Muster REST API instead of
opening the database itself. This keeps validation, task dispatch, and
lifecycle rules behind the same boundary used by the web UI.
"""
from __future__ import annotations

import os
import uuid
from typing import Annotated, Any, Literal

import httpx
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field

Backend = Literal["codex", "claude_code"]
RuntimeMode = Literal["structured", "interactive"]
TaskStatus = Literal[
    "queued",
    "running",
    "waiting_on_you",
    "done",
    "failed",
    "cancelled",
]


class MusterApiClient:
    """Small async client for the loopback Muster API."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        port = os.environ.get("MUSTER_BACKEND_PORT", "8080")
        self.base_url = (
            base_url or os.environ.get("MUSTER_API_URL") or f"http://127.0.0.1:{port}"
        ).rstrip("/")
        self.transport = transport
        self.timeout = timeout

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                transport=self.transport,
                timeout=self.timeout,
            ) as client:
                response = await client.request(method, path, params=params, json=json)
        except httpx.RequestError as exc:
            raise ToolError(
                f"Muster API is unavailable at {self.base_url}: {exc}"
            ) from exc

        if response.is_error:
            detail: Any = None
            try:
                payload = response.json()
                detail = payload.get("detail") if isinstance(payload, dict) else payload
            except ValueError:
                detail = response.text.strip()
            message = detail or response.reason_phrase or "request failed"
            raise ToolError(f"Muster API returned {response.status_code}: {message}")

        if response.status_code == 204 or not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise ToolError("Muster API returned a non-JSON response") from exc

    async def resolve_project(self, project: str) -> dict[str, Any]:
        value = project.strip()
        if not value:
            raise ToolError("Project name or ID is required")
        payload = await self.request("GET", "/api/projects")
        projects = payload.get("items", []) if isinstance(payload, dict) else []

        by_id = [item for item in projects if str(item.get("id")) == value]
        if by_id:
            return by_id[0]

        by_name = [
            item
            for item in projects
            if str(item.get("name", "")).casefold() == value.casefold()
        ]
        if len(by_name) == 1:
            return by_name[0]
        if len(by_name) > 1:
            raise ToolError(
                f"More than one Muster project is named {value!r}; use a project ID"
            )
        raise ToolError(f"Muster project not found: {value}")


def _task_id(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError) as exc:
        raise ToolError(f"Invalid task ID: {value}") from exc


def _task_summary(task: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "id",
        "project_id",
        "title",
        "status",
        "attention_reason",
        "backend",
        "runtime_mode",
        "model",
        "tags",
        "updated_at",
    )
    return {field: task.get(field) for field in fields}


def build_server(api: MusterApiClient | None = None) -> MCPServer:
    """Build a server; accepting a client keeps protocol tests in-process."""

    client = api or MusterApiClient()
    server = MCPServer(
        "Muster",
        instructions=(
            "Use Muster projects to dispatch work to local Codex or Claude Code runtimes. "
            "Creating a task starts an agent immediately with that project's configured "
            "working directory and capabilities."
        ),
    )

    @server.tool()
    async def list_projects() -> dict[str, Any]:
        """List projects available for task creation and their default runtimes."""

        payload = await client.request("GET", "/api/projects")
        items = payload.get("items", []) if isinstance(payload, dict) else []
        fields = (
            "id",
            "name",
            "description",
            "default_backend",
            "default_model",
            "primary_directory_id",
        )
        return {
            "items": [
                {field: project.get(field) for field in fields} for project in items
            ]
        }

    @server.tool()
    async def create_task(
        project: str,
        title: str,
        prompt: str,
        backend: Backend | None = None,
        runtime_mode: RuntimeMode | None = None,
        model: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create and immediately dispatch a task in a project.

        ``project`` accepts an exact project name or UUID. The project supplies
        the working directory, skills, MCP connectors, and tool policy. Omit
        backend/runtime/model to use the project's configured defaults.
        """

        selected = await client.resolve_project(project)
        body: dict[str, Any] = {
            "title": title.strip(),
            "initial_prompt": prompt.strip(),
            "tags": tags or [],
        }
        if not body["title"]:
            raise ToolError("Task title must not be empty")
        if not body["initial_prompt"]:
            raise ToolError("Task prompt must not be empty")
        if backend is not None:
            body["backend"] = backend
        if runtime_mode is not None:
            body["runtime_mode"] = runtime_mode
        if model is not None:
            body["model"] = model
        return await client.request(
            "POST", f"/api/projects/{selected['id']}/tasks", json=body
        )

    @server.tool()
    async def list_tasks(
        project: str | None = None,
        status: TaskStatus | None = None,
        limit: Annotated[int, Field(ge=1, le=200)] = 50,
    ) -> dict[str, Any]:
        """List recent tasks, optionally filtered by project and status."""

        params = {"status": status} if status is not None else None
        if project is None:
            payload = await client.request("GET", "/api/tasks", params=params)
        else:
            selected = await client.resolve_project(project)
            payload = await client.request(
                "GET", f"/api/projects/{selected['id']}/tasks", params=params
            )
        items = payload.get("items", []) if isinstance(payload, dict) else []
        items.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
        return {"items": [_task_summary(item) for item in items[:limit]]}

    @server.tool()
    async def get_task(task_id: str) -> dict[str, Any]:
        """Get the complete current state and original prompt for one task."""

        return await client.request("GET", f"/api/tasks/{_task_id(task_id)}")

    @server.tool()
    async def send_task_message(task_id: str, message: str) -> dict[str, Any]:
        """Send a follow-up message and resume the task's configured agent."""

        content = message.strip()
        if not content:
            raise ToolError("Message must not be empty")
        return await client.request(
            "POST",
            f"/api/tasks/{_task_id(task_id)}/messages",
            json={"content_text": content, "media": []},
        )

    @server.tool()
    async def cancel_task(task_id: str) -> dict[str, Any]:
        """Cancel a queued or running task and stop its agent process."""

        return await client.request(
            "POST", f"/api/tasks/{_task_id(task_id)}/cancel"
        )

    @server.tool()
    async def complete_task(task_id: str) -> dict[str, Any]:
        """Explicitly mark a reviewed task complete, subject to its PR policy."""

        return await client.request(
            "POST", f"/api/tasks/{_task_id(task_id)}/complete"
        )

    return server


mcp = build_server()


def main() -> None:
    """Run the local process-spawned MCP transport."""

    mcp.run()


if __name__ == "__main__":
    main()
