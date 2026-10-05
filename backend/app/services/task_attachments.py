"""Storage, validation, and runtime prompt rendering for task attachments."""
from __future__ import annotations

import asyncio
import re
import shutil
import time
import uuid
from pathlib import Path

import anyio
from fastapi import HTTPException, UploadFile

from app.config import settings
from app.schemas.task import TaskAttachment

MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
MAX_STORAGE_BYTES = 2 * 1024 * 1024 * 1024
MAX_STORAGE_OBJECTS = 1000
PENDING_TTL_SECONDS = 24 * 60 * 60
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]+")
_upload_lock = asyncio.Lock()


def _root() -> Path:
    return (settings.media_dir / "task-attachments").resolve()


def _safe_filename(value: str | None) -> str:
    name = Path(value or "attachment").name.strip() or "attachment"
    return (_SAFE_NAME.sub("_", name)[:255] or "attachment").strip(". ") or "attachment"


async def save_upload(upload: UploadFile) -> TaskAttachment:
    async with _upload_lock:
        root = _root()
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        root.chmod(0o700)
        _cleanup_expired_pending(root)
        if sum(1 for path in root.iterdir() if path.is_dir()) >= MAX_STORAGE_OBJECTS:
            raise HTTPException(status_code=507, detail="Task attachment storage has too many files")
        stored_bytes = _storage_usage(root)
        name = _safe_filename(upload.filename)
        attachment_id = uuid.uuid4()
        directory = root / str(attachment_id)
        directory.mkdir(mode=0o700)
        target = directory / name
        size = 0
        try:
            async with await anyio.open_file(target, "wb") as output:
                target.chmod(0o600)
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_ATTACHMENT_BYTES:
                        raise HTTPException(status_code=413, detail="Attachments must be 25 MB or smaller")
                    if stored_bytes + size > MAX_STORAGE_BYTES:
                        raise HTTPException(status_code=507, detail="Task attachment storage is full")
                    await output.write(chunk)
        except Exception:
            target.unlink(missing_ok=True)
            directory.rmdir()
            raise
        finally:
            await upload.close()
    return TaskAttachment(
        name=name,
        path=str(target),
        mime=upload.content_type or "application/octet-stream",
        size=size,
        url=f"/api/task-attachments/{attachment_id}/{name}",
    )


def validate(attachments: list[TaskAttachment]) -> list[dict]:
    root = _root()
    result: list[dict] = []
    for attachment in attachments:
        path = Path(attachment.path).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise HTTPException(status_code=422, detail=f"Attachment is unavailable: {attachment.name}")
        if (path.parent / ".claimed").exists():
            raise HTTPException(status_code=409, detail=f"Attachment is already assigned: {attachment.name}")
        expected_url = f"/api/task-attachments/{path.parent.name}/{path.name}"
        if attachment.url != expected_url or attachment.name != path.name or path.stat().st_size != attachment.size:
            raise HTTPException(status_code=422, detail=f"Attachment metadata is invalid: {attachment.name}")
        result.append({**attachment.model_dump(), "path": str(path)})
    return result


def claim(attachments: list[dict], task_id: uuid.UUID) -> None:
    root = _root()
    claimed: list[Path] = []
    try:
        for item in attachments:
            path = Path(item["path"]).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                raise HTTPException(status_code=422, detail="Attachment is unavailable")
            marker = path.parent / ".claimed"
            with marker.open("x", encoding="utf-8") as output:
                output.write(str(task_id))
            marker.chmod(0o400)
            path.chmod(0o400)
            path.parent.chmod(0o500)
            claimed.append(path)
    except FileExistsError as exc:
        release(claimed, task_id)
        raise HTTPException(status_code=409, detail="Attachment is already assigned") from exc
    except Exception:
        release(claimed, task_id)
        raise


def release(attachments: list | list[Path], task_id: uuid.UUID) -> None:
    root = _root()
    for item in attachments:
        path = item if isinstance(item, Path) else Path(item["path"]).resolve()
        marker = path.parent / ".claimed"
        if not path.is_relative_to(root) or not marker.is_file():
            continue
        if marker.read_text(encoding="utf-8") != str(task_id):
            continue
        path.parent.chmod(0o700)
        path.chmod(0o600)
        marker.unlink()


def delete(attachments: list | None, task_id: uuid.UUID) -> None:
    root = _root()
    directories: set[Path] = set()
    for item in attachments or []:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            continue
        path = Path(item["path"]).resolve()
        marker = path.parent / ".claimed"
        if (
            path.is_relative_to(root)
            and path.parent.parent == root
            and marker.is_file()
            and marker.read_text(encoding="utf-8") == str(task_id)
        ):
            directories.add(path.parent)
    for directory in directories:
        if directory.is_dir():
            directory.chmod(0o700)
            for child in directory.iterdir():
                child.chmod(0o600)
            shutil.rmtree(directory)


def render_prompt(prompt: str, media: list | None) -> str:
    attachments = [
        item for item in (media or [])
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    ]
    if not attachments:
        return prompt
    lines = [
        f'- {item.get("name") or Path(item["path"]).name} '
        f'({item.get("mime") or "application/octet-stream"}): {item["path"]}'
        for item in attachments
    ]
    return (
        f"{prompt}\n\nAttached files are available at these absolute paths. "
        "Inspect them as part of the task; images may be opened with your image-viewing tools.\n"
        + "\n".join(lines)
    )


def resolve_download(attachment_id: uuid.UUID, filename: str) -> Path:
    root = _root()
    path = (root / str(attachment_id) / _safe_filename(filename)).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(status_code=404, detail="Attachment not found")
    return path


def attachment_directories(media: list | None) -> list[str]:
    root = _root()
    return list(dict.fromkeys(
        str(path.parent)
        for item in (media or [])
        if isinstance(item, dict)
        and isinstance(item.get("path"), str)
        and (path := Path(item["path"]).resolve()).is_relative_to(root)
        and path.is_file()
    ))


def _storage_usage(root: Path) -> int:
    return sum(path.stat().st_size for path in root.glob("*/*") if path.is_file())


def cleanup_expired_pending() -> None:
    root = _root()
    if root.is_dir():
        _cleanup_expired_pending(root)


def _cleanup_expired_pending(root: Path) -> None:
    cutoff = time.time() - PENDING_TTL_SECONDS
    for directory in root.iterdir():
        if not directory.is_dir() or (directory / ".claimed").exists():
            continue
        if directory.stat().st_mtime < cutoff:
            shutil.rmtree(directory)
