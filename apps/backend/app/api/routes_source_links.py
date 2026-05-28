from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.api.schemas import SourceLinkCreate, SourceLinkPatch
from app.core.config import settings
from app.core.exceptions import not_found
from app.core.security import AdminAuth
from app.db.models import AdminUser, Audience, CampaignSource, ClientStatus, Lead, Touchpoint
from app.db.session import get_db

router = APIRouter(prefix="/api/admin/links", tags=["admin-links"])


SOURCE_LABELS = {
    "instagram": "Instagram",
    "telegram": "Telegram",
    "tiktok": "TikTok",
    "whatsapp": "WhatsApp",
    "facebook": "Facebook",
    "youtube": "YouTube",
    "website": "Сайт",
    "offline": "Офлайн",
    "other": "Другое",
}


def _clean_slug(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-_").lower()
    if not cleaned:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Slug обязателен")
    if len(cleaned) > 64:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Slug должен быть не длиннее 64 символов")
    return cleaned


def _clean_text(value: str | None, limit: int = 255) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.strip().split())
    return cleaned[:limit] or None


def _full_url(slug: str) -> str:
    bot_name = settings.telegram_bot_username or "YOUR_BOT_USERNAME"
    return f"https://t.me/{bot_name}?start={slug}"


def _source_link_query(db: Session):
    return db.query(CampaignSource).options(selectinload(CampaignSource.audience), selectinload(CampaignSource.assigned_manager))


def _link_metrics(db: Session, link: CampaignSource) -> dict[str, Any]:
    unique_users = db.query(func.count(func.distinct(Touchpoint.lead_id))).filter(Touchpoint.source_link_id == link.id).scalar() or 0
    new_users = db.query(Lead).filter(Lead.first_source_link_id == link.id).count()
    applications = db.query(Lead).filter(Lead.first_source_link_id == link.id, Lead.crm_status == ClientStatus.APPLIED).count()
    purchases = db.query(Lead).filter(Lead.first_source_link_id == link.id, Lead.crm_status == ClientStatus.BOUGHT).count()
    last_touch = db.query(func.max(Touchpoint.created_at)).filter(Touchpoint.source_link_id == link.id).scalar()
    clicks = link.clicks or db.query(Touchpoint).filter(Touchpoint.source_link_id == link.id).count()
    return {
        "clicks": clicks,
        "unique_users": unique_users,
        "new_users": new_users,
        "applications": applications,
        "purchases": purchases,
        "click_to_application": round(applications / clicks * 100, 2) if clicks else 0,
        "application_to_purchase": round(purchases / applications * 100, 2) if applications else 0,
        "last_touch_at": last_touch,
    }


def _source_link_dict(db: Session, link: CampaignSource) -> dict[str, Any]:
    metrics = _link_metrics(db, link)
    return {
        "id": link.id,
        "name": link.title,
        "slug": link.slug,
        "start_payload": link.start_payload,
        "full_url": link.url or _full_url(link.start_payload or link.slug),
        "source": link.source,
        "source_label": SOURCE_LABELS.get(link.source or "", link.source or "Другое"),
        "campaign": link.campaign,
        "description": link.description,
        "audience": {"id": link.audience.id, "name": link.audience.name, "color": link.audience.color} if link.audience else None,
        "tags": link.auto_tags or [],
        "funnel_id": link.funnel_id,
        "assigned_manager": {"id": link.assigned_manager.id, "email": link.assigned_manager.email} if link.assigned_manager else None,
        "is_active": link.is_active,
        "created_at": link.created_at,
        "updated_at": link.updated_at,
        "metrics": metrics,
    }


def _ensure_link_references(db: Session, audience_id: int | None, manager_id: int | None) -> None:
    if audience_id and not db.query(Audience).filter(Audience.id == audience_id).first():
        raise not_found("База не найдена")
    if manager_id and not db.query(AdminUser).filter(AdminUser.id == manager_id, AdminUser.is_active.is_(True)).first():
        raise not_found("Менеджер не найден")


@router.get("/stats")
def links_stats(_: AdminAuth, db: Session = Depends(get_db)) -> dict:
    links = db.query(CampaignSource).all()
    totals = {"clicks": 0, "unique_users": 0, "new_users": 0, "applications": 0, "purchases": 0}
    best: dict[str, Any] | None = None
    for link in links:
        metrics = _link_metrics(db, link)
        for key in totals:
            totals[key] += metrics[key]
        score = metrics["click_to_application"]
        if best is None or score > best["conversion"]:
            best = {"id": link.id, "name": link.title, "conversion": score}
    return {"totals": totals, "best_link": best}


@router.get("")
def list_source_links(_: AdminAuth, db: Session = Depends(get_db)) -> dict:
    links = _source_link_query(db).order_by(CampaignSource.created_at.desc()).all()
    return {"items": [_source_link_dict(db, item) for item in links], "sources": [{"value": value, "label": label} for value, label in SOURCE_LABELS.items()]}


@router.post("")
def create_source_link(payload: SourceLinkCreate, _: AdminAuth, db: Session = Depends(get_db)) -> dict:
    slug = _clean_slug(payload.slug)
    _ensure_link_references(db, payload.audience_id, payload.assigned_manager_id)
    existing = db.query(CampaignSource).filter((CampaignSource.slug == slug) | (CampaignSource.start_payload == slug)).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ссылка с таким кодом уже существует")
    link = CampaignSource(
        slug=slug,
        title=_clean_text(payload.name) or slug,
        start_payload=slug,
        url=_full_url(slug),
        source=payload.source,
        campaign=_clean_text(payload.campaign),
        description=payload.description,
        audience_id=payload.audience_id,
        auto_tags=[item.strip() for item in payload.tags if item.strip()],
        funnel_id=payload.funnel_id,
        assigned_manager_id=payload.assigned_manager_id,
        is_active=payload.is_active,
    )
    db.add(link)
    db.commit()
    db.refresh(link)
    return _source_link_dict(db, link)


@router.get("/{link_id}")
def get_source_link(link_id: int, _: AdminAuth, db: Session = Depends(get_db)) -> dict:
    link = _source_link_query(db).filter(CampaignSource.id == link_id).first()
    if not link:
        raise not_found("Ссылка не найдена")
    return _source_link_dict(db, link)


@router.patch("/{link_id}")
def patch_source_link(link_id: int, payload: SourceLinkPatch, _: AdminAuth, db: Session = Depends(get_db)) -> dict:
    link = _source_link_query(db).filter(CampaignSource.id == link_id).first()
    if not link:
        raise not_found("Ссылка не найдена")
    data = payload.model_dump(exclude_unset=True)
    new_slug = data.get("slug")
    if new_slug:
        slug = _clean_slug(new_slug)
        existing = db.query(CampaignSource).filter(CampaignSource.id != link.id, (CampaignSource.slug == slug) | (CampaignSource.start_payload == slug)).first()
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Ссылка с таким кодом уже существует")
        link.slug = slug
        link.start_payload = slug
        link.url = _full_url(slug)
    if "name" in data and data["name"] is not None:
        link.title = _clean_text(data["name"]) or link.title
    for field in ["source", "campaign", "description", "funnel_id", "is_active"]:
        if field in data:
            setattr(link, field, data[field])
    if "audience_id" in data or "assigned_manager_id" in data:
        _ensure_link_references(db, data.get("audience_id", link.audience_id), data.get("assigned_manager_id", link.assigned_manager_id))
    if "audience_id" in data:
        link.audience_id = data["audience_id"]
    if "assigned_manager_id" in data:
        link.assigned_manager_id = data["assigned_manager_id"]
    if "tags" in data and data["tags"] is not None:
        link.auto_tags = [item.strip() for item in data["tags"] if item.strip()]
    db.commit()
    db.refresh(link)
    return _source_link_dict(db, link)


@router.delete("/{link_id}")
def delete_source_link(link_id: int, _: AdminAuth, db: Session = Depends(get_db)) -> dict:
    link = db.query(CampaignSource).filter(CampaignSource.id == link_id).first()
    if not link:
        raise not_found("Ссылка не найдена")
    has_history = (
        db.query(Touchpoint).filter(Touchpoint.source_link_id == link.id).first()
        or db.query(Lead).filter((Lead.first_source_link_id == link.id) | (Lead.last_source_link_id == link.id)).first()
    )
    if has_history:
        link.is_active = False
        db.commit()
        return {"ok": True, "deactivated": True}
    db.delete(link)
    db.commit()
    return {"ok": True, "deactivated": False}
