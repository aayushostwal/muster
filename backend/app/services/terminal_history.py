"""Readable, paginated native conversations, independent of PTY redraws."""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from app.config import settings

_PAGE_ITEMS = 100
_SCAN_BYTES = 2 * 1024 * 1024
_TEXT_LIMIT = 64 * 1024


def history_paths(task_id: uuid.UUID, session_ids: list[str]) -> list[Path]:
    root = settings.backend_sessions_dir / str(task_id) / "codex" / "sessions"
    # Older overlays linked the whole user sessions directory. Never enumerate
    # other tasks through such a shared link.
    owner = settings.backend_sessions_dir.resolve() / str(task_id)
    paths = set(root.rglob("*.jsonl")) if root.resolve().is_relative_to(owner) else set()
    codex = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "sessions"
    claude = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")) / "projects"
    for session_id in session_ids:
        try:
            uuid.UUID(session_id)
        except ValueError:
            continue
        # Adopt older sessions only by their persisted native handle.
        if not any(session_id in path.name for path in paths):
            paths.update(codex.glob(f"**/*{session_id}.jsonl"))
        paths.update(claude.glob(f"*/{session_id}.jsonl"))
    def started(path: Path) -> tuple[str, str]:
        try:
            with path.open("rb") as stream:
                first = json.loads(stream.readline())
            timestamp = first.get("timestamp", "") if isinstance(first, dict) else ""
        except (ValueError, UnicodeDecodeError):
            timestamp = ""
        return str(timestamp), str(path)

    return sorted(paths, key=started)


def _text(value: object) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _entries(event: dict) -> list[dict]:
    timestamp = event.get("timestamp")
    payload = event.get("payload")
    if event.get("type") == "response_item" and isinstance(payload, dict):
        kind = payload.get("type")
        if kind == "message" and payload.get("role") in {"user", "assistant"}:
            return [{"role": payload["role"], "text": "\n".join(
                part["text"] for part in payload.get("content", [])
                if isinstance(part, dict) and isinstance(part.get("text"), str)
            ), "timestamp": timestamp}]
        if kind in {"function_call", "custom_tool_call"}:
            return [{"role": "tool", "text": f'{payload.get("name", "Tool")}\n{_text(payload.get("input", payload.get("arguments", "")))}', "timestamp": timestamp}]
        if kind in {"function_call_output", "custom_tool_call_output"}:
            return [{"role": "tool_result", "text": _text(payload.get("output", "")), "timestamp": timestamp}]
    # Claude's native JSONL uses message content blocks, not Codex events.
    message = event.get("message")
    if event.get("type") in {"user", "assistant"} and isinstance(message, dict):
        content = message.get("content", [])
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]
        entries = []
        for block in content:
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "text":
                role, text = event["type"], block.get("text", "")
            elif kind == "tool_use":
                role, text = "tool", f'{block.get("name", "Tool")}\n{_text(block.get("input", ""))}'
            elif kind == "tool_result":
                role, text = "tool_result", _text(block.get("content", ""))
            else:
                continue
            entries.append({"role": role, "text": text, "timestamp": timestamp})
        return entries
    return []


def read_page(paths: list[Path], cursor: str = "0:0") -> dict:
    try:
        index, offset = map(int, cursor.split(":"))
        if index < 0 or offset < 0 or index > len(paths):
            raise ValueError
    except ValueError as exc:
        raise ValueError("Invalid history cursor") from exc
    items: list[dict] = []
    scanned = 0
    while index < len(paths):
        with paths[index].open("rb") as stream:
            if offset > paths[index].stat().st_size:
                raise ValueError("Invalid history cursor")
            stream.seek(offset)
            while line := stream.readline():
                # Leave an in-progress JSONL record for the next request.
                if not line.endswith(b"\n"):
                    return {"items": items, "next_cursor": None}
                scanned += len(line)
                offset = stream.tell()
                try:
                    event = json.loads(line)
                    entries = _entries(event) if isinstance(event, dict) else []
                except (ValueError, UnicodeDecodeError):
                    entries = []
                for entry in entries:
                    text = entry["text"]
                    if not text:
                        continue
                    entry["truncated"] = len(text) > _TEXT_LIMIT
                    entry["text"] = text[:_TEXT_LIMIT]
                    items.append(entry)
                if len(items) >= _PAGE_ITEMS or scanned >= _SCAN_BYTES:
                    return {"items": items, "next_cursor": f"{index}:{offset}"}
        index += 1
        offset = 0
    return {"items": items, "next_cursor": None}
