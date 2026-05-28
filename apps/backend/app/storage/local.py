from __future__ import annotations

import shutil
from pathlib import Path

from app.core.config import settings


class LocalStorage:
    def __init__(self) -> None:
        self.root = settings.storage_root()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, relative_path: str) -> Path:
        raw_path = Path(relative_path)
        if raw_path.is_absolute() or ".." in raw_path.parts:
            raise ValueError("Unsafe storage path")
        resolved = (self.root / raw_path).resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise ValueError("Unsafe storage path") from exc
        return resolved

    def abs_path(self, relative_path: str) -> str:
        return str(self._resolve(relative_path))

    def save_bytes(self, relative_path: str, data: bytes) -> str:
        target = self._resolve(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return relative_path

    def copy_file(self, source_path: str, relative_path: str) -> str:
        target = self._resolve(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_path, target)
        return relative_path

    def delete_file(self, relative_path: str | None) -> None:
        if not relative_path:
            return
        try:
            self._resolve(relative_path).unlink(missing_ok=True)
        except ValueError:
            return

    def public_url(self, relative_path: str) -> str:
        from app.core.media import sign_media_path

        return f"{settings.backend_url.rstrip('/')}/api/media/{sign_media_path(relative_path)}"


local_storage = LocalStorage()
