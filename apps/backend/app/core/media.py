from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status

from app.core.config import settings


MEDIA_TOKEN_TTL_SECONDS = 60 * 60


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}".encode("ascii"))


def _safe_path(path: str) -> str:
    raw_path = Path(path)
    if raw_path.is_absolute() or ".." in raw_path.parts:
        raise ValueError("Unsafe media path")
    return raw_path.as_posix().lstrip("/")


def sign_media_path(path: str, ttl_seconds: int = MEDIA_TOKEN_TTL_SECONDS) -> str:
    safe_path = _safe_path(path)
    payload = {"p": safe_path, "exp": int(time.time()) + ttl_seconds}
    body = _b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(settings.jwt_secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
    return f"{body}.{_b64encode(signature)}"


def verify_media_token(token: str) -> str:
    try:
        body, signature = token.split(".", 1)
        expected = hmac.new(settings.jwt_secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64decode(signature), expected):
            raise ValueError("Invalid media signature")
        payload: dict[str, Any] = json.loads(_b64decode(body).decode("utf-8"))
        if int(payload.get("exp") or 0) < int(time.time()):
            raise ValueError("Expired media token")
        return _safe_path(str(payload.get("p") or ""))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Media not found") from exc
