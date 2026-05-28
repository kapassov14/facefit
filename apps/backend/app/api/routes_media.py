from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.core.exceptions import not_found
from app.core.media import verify_media_token
from app.storage.local import local_storage

router = APIRouter(prefix="/api/media", tags=["media"])


@router.get("/{media_token}")
def get_media(media_token: str) -> FileResponse:
    relative_path = verify_media_token(media_token)
    abs_path = Path(local_storage.abs_path(relative_path))
    if not abs_path.exists() or not abs_path.is_file():
        raise not_found("Media not found")
    return FileResponse(abs_path)
