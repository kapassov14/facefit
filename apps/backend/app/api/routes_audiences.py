from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.schemas import AudienceCreate, AudiencePatch
from app.core.exceptions import not_found
from app.core.security import AdminAuth
from app.db.models import Audience, Lead
from app.db.session import get_db

router = APIRouter(prefix="/api/admin/audiences", tags=["admin-audiences"])


DEFAULT_AUDIENCES = [
    ("Все пользователи", "Общая база всех клиентов", "#be7d86"),
    ("Instagram leads", "Лиды из Instagram", "#d48aa6"),
    ("Telegram leads", "Лиды из Telegram", "#6f9bd8"),
    ("Прогрев", "Клиенты в прогреве", "#d8b46f"),
    ("Заявки", "Оставили заявку", "#7b967c"),
    ("Клиенты", "Оплатили продукт или консультацию", "#5d8f78"),
    ("Потенциальные покупатели", "Готовы к продаже", "#9d7067"),
    ("VIP", "Приоритетная база", "#8c6dd8"),
    ("Неактивные", "Требуют реактивации", "#9b9b9b"),
]


def _clean_text(value: str | None, limit: int = 255) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.strip().split())
    return cleaned[:limit] or None


def _ensure_default_audiences(db: Session) -> None:
    if db.query(Audience).count():
        return
    for name, description, color in DEFAULT_AUDIENCES:
        db.add(Audience(name=name, description=description, color=color))
    db.commit()


def _audience_dict(db: Session, audience: Audience) -> dict:
    clients_count = db.query(Lead).filter(Lead.audience_id == audience.id).count()
    return {
        "id": audience.id,
        "name": audience.name,
        "description": audience.description,
        "color": audience.color,
        "clients_count": clients_count,
        "created_at": audience.created_at,
        "updated_at": audience.updated_at,
    }


@router.get("")
def list_audiences(_: AdminAuth, db: Session = Depends(get_db)) -> dict:
    _ensure_default_audiences(db)
    audiences = db.query(Audience).order_by(Audience.created_at.asc()).all()
    return {"items": [_audience_dict(db, item) for item in audiences]}


@router.post("")
def create_audience(payload: AudienceCreate, _: AdminAuth, db: Session = Depends(get_db)) -> dict:
    name = _clean_text(payload.name)
    if not name:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Название базы обязательно")
    existing = db.query(Audience).filter(Audience.name == name).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="База с таким названием уже существует")
    audience = Audience(name=name, description=payload.description, color=payload.color)
    db.add(audience)
    db.commit()
    db.refresh(audience)
    return _audience_dict(db, audience)


@router.patch("/{audience_id}")
def patch_audience(audience_id: int, payload: AudiencePatch, _: AdminAuth, db: Session = Depends(get_db)) -> dict:
    audience = db.query(Audience).filter(Audience.id == audience_id).first()
    if not audience:
        raise not_found("База не найдена")
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        name = _clean_text(data["name"])
        if not name:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Название базы обязательно")
        existing = db.query(Audience).filter(Audience.id != audience.id, Audience.name == name).first()
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="База с таким названием уже существует")
        audience.name = name
    if "description" in data:
        audience.description = data["description"]
    if "color" in data and data["color"] is not None:
        audience.color = data["color"]
    db.commit()
    db.refresh(audience)
    return _audience_dict(db, audience)


@router.delete("/{audience_id}")
def delete_audience(audience_id: int, _: AdminAuth, db: Session = Depends(get_db)) -> dict:
    audience = db.query(Audience).filter(Audience.id == audience_id).first()
    if not audience:
        raise not_found("База не найдена")
    clients_count = db.query(Lead).filter(Lead.audience_id == audience.id).count()
    if clients_count:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Нельзя удалить базу, в которой есть клиенты")
    db.delete(audience)
    db.commit()
    return {"ok": True}
