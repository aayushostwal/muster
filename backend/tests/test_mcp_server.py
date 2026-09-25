from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from mcp import Client, StdioServerParameters
from mcp.server.mcpserver.exceptions import ToolError

from app.mcp_server import MusterApiClient, build_server


PROJECT_ID = "11111111-1111-4111-8111-111111111111"
TASK_ID = "22222222-2222-4222-8222-222222222222"


def _project() -> dict[str, Any]:
    return {
        "id": PROJECT_ID,
        "name": "Muster",
        "description": "Local agent control plane",
        "default_backend": "codex",
        "default_model": "gpt-5",
        "primary_directory_id": "33333333-3333-4333-8333-333333333333",
    }


def _task(**changes: Any) -> dict[str, Any]:
    task = {
        "id": TASK_ID,
        "project_id": PROJECT_ID,
        "title": "Add an MCP layer",
        "initial_prompt": "Implement and test the MCP server",
        "status": "running",
        "attention_reason": None,
        "backend": "codex",
        "runtime_mode": "structured",
        "model": "gpt-5",
        "fallback_models": [],
        "tags": ["integration"],
        "thinking_level": "medium",
        "agent_id": None,
        "context_strategy": "full",
        "session_id": None,
        "created_at": "2026-09-25T10:00:00Z",
        "updated_at": "2026-09-25T10:01:00Z",
        "started_at": "2026-09-25T10:00:01Z",
        "completed_at": None,
        "cron_job_id": None,
    }
    task.update(changes)
    return task


@pytest.mark.asyncio
async def test_lists_expected_tools_and_projects() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/projects"
        return httpx.Response(200, json={"items": [_project()]})

    api = MusterApiClient(
        base_url="http://muster.test", transport=httpx.MockTransport(handler)
    )
    async with Client(build_server(api), raise_exceptions=True) as client:
        tools = await client.list_tools()
        assert {tool.name for tool in tools.tools} == {
            "list_projects",
            "create_task",
            "list_tasks",
            "get_task",
            "send_task_message",
            "cancel_task",
            "complete_task",
        }

        result = await client.call_tool("list_projects", {})

    assert not result.is_error
    assert result.structured_content == {
        "items": [
            {
                "id": PROJECT_ID,
                "name": "Muster",
                "description": "Local agent control plane",
                "default_backend": "codex",
                "default_model": "gpt-5",
                "primary_directory_id": "33333333-3333-4333-8333-333333333333",
            }
        ]
    }


@pytest.mark.asyncio
async def test_create_task_resolves_project_name_and_dispatches_via_api() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET" and request.url.path == "/api/projects":
            return httpx.Response(200, json={"items": [_project()]})
        if request.method == "POST" and request.url.path == f"/api/projects/{PROJECT_ID}/tasks":
            return httpx.Response(201, json=_task(backend="claude_code", model="sonnet"))
        return httpx.Response(404, json={"detail": "unexpected test request"})

    api = MusterApiClient(
        base_url="http://muster.test", transport=httpx.MockTransport(handler)
    )
    async with Client(build_server(api), raise_exceptions=True) as client:
        result = await client.call_tool(
            "create_task",
            {
                "project": "mUsTeR",
                "title": "  Add an MCP layer  ",
                "prompt": "  Implement and test the MCP server  ",
                "backend": "claude_code",
                "runtime_mode": "interactive",
                "model": "sonnet",
                "tags": ["integration"],
            },
        )

    assert not result.is_error
    assert result.structured_content is not None
    assert result.structured_content["id"] == TASK_ID
    assert [request.method for request in requests] == ["GET", "POST"]
    assert json.loads(requests[1].content) == {
        "title": "Add an MCP layer",
        "initial_prompt": "Implement and test the MCP server",
        "tags": ["integration"],
        "backend": "claude_code",
        "runtime_mode": "interactive",
        "model": "sonnet",
    }


@pytest.mark.asyncio
async def test_task_tools_map_to_lifecycle_endpoints() -> None:
    requests: list[httpx.Request] = []
    older_id = "44444444-4444-4444-8444-444444444444"

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if path == "/api/projects":
            return httpx.Response(200, json={"items": [_project()]})
        if path == f"/api/projects/{PROJECT_ID}/tasks":
            return httpx.Response(
                200,
                json={
                    "items": [
                        _task(id=older_id, updated_at="2026-09-25T09:00:00Z"),
                        _task(),
                    ]
                },
            )
        if request.method == "GET" and path == f"/api/tasks/{TASK_ID}":
            return httpx.Response(200, json=_task())
        if path == f"/api/tasks/{TASK_ID}/messages":
            return httpx.Response(
                201,
                json={
                    "id": str(uuid.uuid4()),
                    "task_id": TASK_ID,
                    "sender": "user",
                    "content_text": "Continue with the tests",
                },
            )
        if path == f"/api/tasks/{TASK_ID}/cancel":
            return httpx.Response(200, json=_task(status="cancelled"))
        if path == f"/api/tasks/{TASK_ID}/complete":
            return httpx.Response(200, json=_task(status="done"))
        return httpx.Response(404, json={"detail": "unexpected test request"})

    api = MusterApiClient(
        base_url="http://muster.test", transport=httpx.MockTransport(handler)
    )
    async with Client(build_server(api), raise_exceptions=True) as client:
        listed = await client.call_tool(
            "list_tasks", {"project": PROJECT_ID, "status": "running", "limit": 1}
        )
        fetched = await client.call_tool("get_task", {"task_id": TASK_ID})
        messaged = await client.call_tool(
            "send_task_message",
            {"task_id": TASK_ID, "message": "  Continue with the tests  "},
        )
        cancelled = await client.call_tool("cancel_task", {"task_id": TASK_ID})
        completed = await client.call_tool("complete_task", {"task_id": TASK_ID})

    assert listed.structured_content is not None
    assert [task["id"] for task in listed.structured_content["items"]] == [TASK_ID]
    assert fetched.structured_content is not None
    assert fetched.structured_content["initial_prompt"] == "Implement and test the MCP server"
    assert messaged.structured_content is not None
    assert messaged.structured_content["content_text"] == "Continue with the tests"
    assert cancelled.structured_content is not None
    assert cancelled.structured_content["status"] == "cancelled"
    assert completed.structured_content is not None
    assert completed.structured_content["status"] == "done"
    assert requests[1].url.params["status"] == "running"
    assert json.loads(requests[3].content) == {
        "content_text": "Continue with the tests",
        "media": [],
    }


@pytest.mark.asyncio
async def test_tool_errors_are_readable_to_mcp_clients() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/projects":
            return httpx.Response(200, json={"items": []})
        return httpx.Response(422, json={"detail": "PR approval is required"})

    api = MusterApiClient(
        base_url="http://muster.test", transport=httpx.MockTransport(handler)
    )
    async with Client(build_server(api)) as client:
        missing = await client.call_tool(
            "create_task",
            {"project": "missing", "title": "Work", "prompt": "Do work"},
        )
        invalid_id = await client.call_tool("complete_task", {"task_id": "not-a-uuid"})
        gated = await client.call_tool("complete_task", {"task_id": TASK_ID})

    assert missing.is_error
    assert "Muster project not found: missing" in missing.content[0].text
    assert invalid_id.is_error
    assert "Invalid task ID: not-a-uuid" in invalid_id.content[0].text
    assert gated.is_error
    assert "Muster API returned 422: PR approval is required" in gated.content[0].text


@pytest.mark.asyncio
async def test_create_task_defaults_and_blank_input_validation() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/api/projects":
            return httpx.Response(200, json={"items": [_project()]})
        return httpx.Response(201, json=_task(tags=[]))

    api = MusterApiClient(
        base_url="http://muster.test", transport=httpx.MockTransport(handler)
    )
    async with Client(build_server(api)) as client:
        created = await client.call_tool(
            "create_task",
            {"project": PROJECT_ID, "title": "Small task", "prompt": "Do it"},
        )
        blank_title = await client.call_tool(
            "create_task",
            {"project": PROJECT_ID, "title": "  ", "prompt": "Do it"},
        )
        blank_prompt = await client.call_tool(
            "create_task",
            {"project": PROJECT_ID, "title": "Small task", "prompt": "  "},
        )
        blank_message = await client.call_tool(
            "send_task_message", {"task_id": TASK_ID, "message": "  "}
        )

    assert not created.is_error
    assert json.loads(requests[1].content) == {
        "title": "Small task",
        "initial_prompt": "Do it",
        "tags": [],
    }
    assert blank_title.is_error
    assert "Task title must not be empty" in blank_title.content[0].text
    assert blank_prompt.is_error
    assert "Task prompt must not be empty" in blank_prompt.content[0].text
    assert blank_message.is_error
    assert "Message must not be empty" in blank_message.content[0].text


@pytest.mark.asyncio
async def test_global_task_listing_forwards_status_and_sorts_results() -> None:
    older_id = "44444444-4444-4444-8444-444444444444"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/tasks"
        assert request.url.params["status"] == "done"
        return httpx.Response(
            200,
            json={
                "items": [
                    _task(id=older_id, updated_at="2026-09-25T09:00:00Z"),
                    _task(status="done"),
                ]
            },
        )

    api = MusterApiClient(
        base_url="http://muster.test", transport=httpx.MockTransport(handler)
    )
    async with Client(build_server(api), raise_exceptions=True) as client:
        result = await client.call_tool("list_tasks", {"status": "done"})

    assert result.structured_content is not None
    assert [task["id"] for task in result.structured_content["items"]] == [
        TASK_ID,
        older_id,
    ]


@pytest.mark.asyncio
async def test_ambiguous_and_blank_projects_return_actionable_errors() -> None:
    duplicate = _project() | {
        "id": "55555555-5555-4555-8555-555555555555",
        "name": "muster",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"items": [_project(), duplicate]})

    api = MusterApiClient(
        base_url="http://muster.test", transport=httpx.MockTransport(handler)
    )
    async with Client(build_server(api)) as client:
        ambiguous = await client.call_tool(
            "create_task",
            {"project": "Muster", "title": "Work", "prompt": "Do work"},
        )
        blank = await client.call_tool(
            "create_task",
            {"project": "  ", "title": "Work", "prompt": "Do work"},
        )

    assert ambiguous.is_error
    assert (
        "More than one Muster project is named 'Muster'; use a project ID"
        in ambiguous.content[0].text
    )
    assert blank.is_error
    assert "Project name or ID is required" in blank.content[0].text


@pytest.mark.asyncio
async def test_api_client_normalizes_transport_and_response_failures() -> None:
    def offline(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    unavailable = MusterApiClient(
        base_url="http://muster.test", transport=httpx.MockTransport(offline)
    )
    with pytest.raises(ToolError, match="Muster API is unavailable.*connection refused"):
        await unavailable.request("GET", "/api/projects")

    responses = iter(
        [
            httpx.Response(502, text="upstream unavailable"),
            httpx.Response(204),
            httpx.Response(200, text="not json"),
        ]
    )

    def response_sequence(request: httpx.Request) -> httpx.Response:
        return next(responses)

    api = MusterApiClient(
        base_url="http://muster.test",
        transport=httpx.MockTransport(response_sequence),
    )
    with pytest.raises(ToolError, match="Muster API returned 502: upstream unavailable"):
        await api.request("GET", "/api/projects")
    assert await api.request("POST", f"/api/tasks/{TASK_ID}/cancel") == {}
    with pytest.raises(ToolError, match="Muster API returned a non-JSON response"):
        await api.request("GET", "/api/projects")


@pytest.mark.asyncio
async def test_server_completes_a_real_stdio_handshake() -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "app.mcp_server"],
        cwd=str(backend_dir),
    )

    async with Client(params, raise_exceptions=True) as client:
        tools = await client.list_tools()

    assert {tool.name for tool in tools.tools} == {
        "list_projects",
        "create_task",
        "list_tasks",
        "get_task",
        "send_task_message",
        "cancel_task",
        "complete_task",
    }
