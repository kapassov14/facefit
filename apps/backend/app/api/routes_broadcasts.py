from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.api.schemas import BroadcastCreate, BroadcastPatch, BroadcastTestSend
from app.api.serializers import broadcast_dict
from app.core.exceptions import not_found
from app.core.security import AdminAuth, require_write_access
from app.db.models import AdminRole, AudienceBase, Broadcast, BroadcastRecipient, TelegramUser
from app.db.session import get_db
from app.workers.tasks_broadcast import enqueue_broadcast, send_test_broadcast_async

router = APIRouter(prefix="/api/broadcasts", tags=["broadcasts"])
admin_router = APIRouter(prefix="/api/admin/broadcasts", tags=["admin-broadcasts"])


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Неверный формат даты") from exc


def _require_broadcast_access(admin) -> None:
    require_write_access(admin)
    if admin.role in {AdminRole.OWNER, AdminRole.ADMIN}:
        return
    if admin.can_broadcast:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Нет прав на рассылки")


def _broadcast_payload(payload: BroadcastCreate | BroadcastPatch) -> dict[str, Any]:
    data = payload.model_dump(exclude_unset=True)
    if "message_text" not in data and data.get("text") is not None:
        data["message_text"] = data["text"]
    if "text" not in data and data.get("message_text") is not None:
        data["text"] = data["message_text"]
    if "buttons_json" not in data and data.get("buttons") is not None:
        data["buttons_json"] = data["buttons"]
    if "buttons" not in data and data.get("buttons_json") is not None:
        data["buttons"] = data["buttons_json"]
    if "media_type" not in data and data.get("message_type") in {"photo", "video", "document"}:
        data["media_type"] = data.get("message_type")
    if "scheduled_at" in data:
        data["scheduled_at"] = _parse_datetime(data["scheduled_at"])
    return data


def _list_broadcasts(db: Session, page: int, page_size: int) -> dict:
    query = db.query(Broadcast).options(
        selectinload(Broadcast.base),
        selectinload(Broadcast.created_by),
        selectinload(Broadcast.recipients),
    ).order_by(Broadcast.created_at.desc())
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [broadcast_dict(item) for item in items], "total": total, "page": page, "page_size": page_size}


def _create_broadcast(payload: BroadcastCreate, admin: AdminAuth, db: Session) -> dict:
    _require_broadcast_access(admin)
    data = _broadcast_payload(payload)
    if data.get("base_id") and not db.query(AudienceBase).filter(AudienceBase.id == data["base_id"]).first():
        raise not_found("База не найдена")
    broadcast = Broadcast(**data, status="scheduled" if data.get("scheduled_at") else "draft", created_by_id=admin.id)
    db.add(broadcast)
    db.commit()
    db.refresh(broadcast)
    return broadcast_dict(broadcast)


def _send_broadcast(broadcast_id: int, admin: AdminAuth, db: Session) -> dict:
    _require_broadcast_access(admin)
    broadcast = db.query(Broadcast).filter(Broadcast.id == broadcast_id).first()
    if not broadcast:
        raise not_found("Рассылка не найдена")
    if broadcast.status in {"sending", "completed"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Рассылка уже отправляется или завершена")
    broadcast.status = "queued"
    db.commit()
    enqueue_broadcast(broadcast_id)
    return {"ok": True, "status": "queued"}


@router.get("")
def list_broadcasts(_: AdminAuth, db: Session = Depends(get_db), page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100)) -> dict:
    return _list_broadcasts(db, page, page_size)


@router.post("")
def create_broadcast(payload: BroadcastCreate, admin: AdminAuth, db: Session = Depends(get_db)) -> dict:
    return _create_broadcast(payload, admin, db)


@router.post("/{broadcast_id}/send")
def send_broadcast(broadcast_id: int, admin: AdminAuth, db: Session = Depends(get_db)) -> dict:
    return _send_broadcast(broadcast_id, admin, db)


@admin_router.get("")
def admin_list_broadcasts(_: AdminAuth, db: Session = Depends(get_db), page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100)) -> dict:
    return _list_broadcasts(db, page, page_size)


@admin_router.post("")
def admin_create_broadcast(payload: BroadcastCreate, admin: AdminAuth, db: Session = Depends(get_db)) -> dict:
    return _create_broadcast(payload, admin, db)


@admin_router.get("/{broadcast_id}")
def admin_get_broadcast(broadcast_id: int, _: AdminAuth, db: Session = Depends(get_db)) -> dict:
    broadcast = (
        db.query(Broadcast)
        .options(selectinload(Broadcast.base), selectinload(Broadcast.created_by), selectinload(Broadcast.recipients))
        .filter(Broadcast.id == broadcast_id)
        .first()
    )
    if not broadcast:
        raise not_found("Рассылка не найдена")
    return broadcast_dict(broadcast)


@admin_router.patch("/{broadcast_id}")
def admin_patch_broadcast(broadcast_id: int, payload: BroadcastPatch, admin: AdminAuth, db: Session = Depends(get_db)) -> dict:
    _require_broadcast_access(admin)
    broadcast = db.query(Broadcast).filter(Broadcast.id == broadcast_id).first()
    if not broadcast:
        raise not_found("Рассылка не найдена")
    if broadcast.status in {"sending", "completed"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Нельзя редактировать отправляемую или завершенную рассылку")
    data = _broadcast_payload(payload)
    for key, value in data.items():
        setattr(broadcast, key, value)
    db.commit()
    db.refresh(broadcast)
    return broadcast_dict(broadcast)


@admin_router.post("/{broadcast_id}/send")
def admin_send_broadcast(broadcast_id: int, admin: AdminAuth, db: Session = Depends(get_db)) -> dict:
    return _send_broadcast(broadcast_id, admin, db)


@admin_router.post("/{broadcast_id}/test-send")
def admin_test_send_broadcast(broadcast_id: int, payload: BroadcastTestSend, admin: AdminAuth, db: Session = Depends(get_db)) -> dict:
    _require_broadcast_access(admin)
    broadcast = db.query(Broadcast).filter(Broadcast.id == broadcast_id).first()
    if not broadcast:
        raise not_found("Рассылка не найдена")
    telegram_id = payload.telegram_id
    if payload.admin_id and not telegram_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="У менеджера нет Telegram ID, укажите telegram_id")
    if not telegram_id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Укажите telegram_id для тестовой отправки")
    result = asyncio.run(send_test_broadcast_async(broadcast.id, telegram_id))
    return result


@admin_router.post("/{broadcast_id}/pause")
def admin_pause_broadcast(broadcast_id: int, admin: AdminAuth, db: Session = Depends(get_db)) -> dict:
    _require_broadcast_access(admin)
    broadcast = db.query(Broadcast).filter(Broadcast.id == broadcast_id).first()
    if not broadcast:
        raise not_found("Рассылка не найдена")
    broadcast.status = "paused"
    db.commit()
    return {"ok": True, "status": broadcast.status}


@admin_router.post("/{broadcast_id}/cancel")
def admin_cancel_broadcast(broadcast_id: int, admin: AdminAuth, db: Session = Depends(get_db)) -> dict:
    _require_broadcast_access(admin)
    broadcast = db.query(Broadcast).filter(Broadcast.id == broadcast_id).first()
    if not broadcast:
        raise not_found("Рассылка не найдена")
    broadcast.status = "cancelled"
    db.commit()
    return {"ok": True, "status": broadcast.status}


@admin_router.get("/{broadcast_id}/stats")
def admin_broadcast_stats(broadcast_id: int, _: AdminAuth, db: Session = Depends(get_db)) -> dict:
    if not db.query(Broadcast).filter(Broadcast.id == broadcast_id).first():
        raise not_found("Рассылка не найдена")
    rows = (
        db.query(BroadcastRecipient.status, func.count(BroadcastRecipient.id))
        .filter(BroadcastRecipient.broadcast_id == broadcast_id)
        .group_by(BroadcastRecipient.status)
        .all()
    )
    return {"broadcast_id": broadcast_id, "counts": {status_value: count for status_value, count in rows}}
