"""Upload and download files used as task-creation context."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import FileResponse
from starlette.responses import JSONResponse

from app.schemas.task import TaskAttachment
from app.services import task_attachments

router = APIRouter(prefix="/task-attachments", tags=["task-attachments"])
MAX_UPLOAD_REQUEST_BYTES = task_attachments.MAX_ATTACHMENT_BYTES + 1024 * 1024


class AttachmentUploadLimitMiddleware:
    """Reject attachment bodies before Starlette parses or spools multipart data."""

    def __init__(self, app, max_bytes: int = MAX_UPLOAD_REQUEST_BYTES):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] != "/api/task-attachments":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        length = headers.get(b"content-length")
        if length is not None and int(length) > self.max_bytes:
            return await JSONResponse(
                {"detail": "Attachments must be 25 MB or smaller"}, status_code=413
            )(scope, receive, send)
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _UploadBodyTooLarge
            return message

        try:
            return await self.app(scope, limited_receive, send)
        except _UploadBodyTooLarge:
            return await JSONResponse(
                {"detail": "Attachments must be 25 MB or smaller"}, status_code=413
            )(scope, receive, send)


class _UploadBodyTooLarge(Exception):
    pass


@router.post("", status_code=201, response_model=TaskAttachment)
async def upload_task_attachment(file: UploadFile = File(...)):
    return await task_attachments.save_upload(file)


@router.get("/{attachment_id}/{filename}")
async def download_task_attachment(attachment_id: uuid.UUID, filename: str):
    path = task_attachments.resolve_download(attachment_id, filename)
    return FileResponse(path, filename=path.name)
