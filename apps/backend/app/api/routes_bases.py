from __future__ import annotations

import csv
import io
from datetime import datetime, time
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import String, cast, func, or_
from sqlalchemy.orm import Session, selectinload

from app.api.schemas import AudienceBaseCreate, AudienceBaseMembersPatch, AudienceBasePatch
from app.core.exceptions import not_found
from app.core.security import AdminAuth, require_write_access
from app.db.models import AnalysisRequest, AudienceBase, AudienceBaseMember, Broadcast, Lead, TelegramUser
from app.db.session import get_db

router = APIRouter(prefix="/api/admin/bases", tags=["admin-bases"])


def _clean_text(value: str | None, limit: int = 255) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.strip().split())
    return cleaned[:limit] or None


def _parse_datetime(value: str | None, end_of_day: bool = False) -> datetime | None:
    if not value:
        return None
    try:
        if len(value) == 10:
            parsed = datetime.fromisoformat(value).date()
            return datetime.combine(parsed, time.max if end_of_day else time.min)
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Неверный формат даты") from exc


def _apply_dynamic_filters(query, db: Session, filters: dict[str, Any]):
    if filters.get("status"):
        values = filters["status"] if isinstance(filters["status"], list) else [filters["status"]]
        query = query.filter(Lead.crm_status.in_(values))
    if filters.get("problem"):
        problem = str(filters["problem"])
        if db.bind and db.bind.dialect.name == "postgresql":
            query = query.filter(Lead.selected_problems.contains([problem]))
        else:
            query = query.filter(cast(Lead.selected_problems, String).ilike(f"%{problem}%"))
    if filters.get("report_opened") is not None:
        query = query.filter(Lead.report_opened.is_(bool(filters["report_opened"])))
    if filters.get("cta_clicked") is not None:
        query = query.filter(Lead.cta_clicked.is_(bool(filters["cta_clicked"])))
    if filters.get("tag"):
        tag = str(filters["tag"])
        if db.bind and db.bind.dialect.name == "postgresql":
            query = query.filter(Lead.tags.contains([tag]))
        else:
            query = query.filter(cast(Lead.tags, String).ilike(f"%{tag}%"))
    if filters.get("source"):
        query = query.filter(Lead.source == filters["source"])
    if filters.get("campaign"):
        query = query.filter(cast(Lead.utm, String).ilike(f"%{filters['campaign']}%"))
    if filters.get("manager_id"):
        query = query.filter(Lead.assigned_manager_id == int(filters["manager_id"]))
    if filters.get("after_photo_status"):
        query = query.filter(Lead.analyses.any(AnalysisRequest.after_photo_status == str(filters["after_photo_status"])))
    created_from = _parse_datetime(filters.get("created_from"))
    created_to = _parse_datetime(filters.get("created_to"), end_of_day=True)
    if created_from:
        query = query.filter(Lead.created_at >= created_from)
    if created_to:
        query = query.filter(Lead.created_at <= created_to)
    return query


def _base_lead_query(db: Session, base: AudienceBase):
    query = db.query(Lead).options(selectinload(Lead.telegram_user), selectinload(Lead.assigned_manager))
    if base.type == "dynamic":
        return _apply_dynamic_filters(query, db, base.filters_json or {})
    return query.join(AudienceBaseMember, AudienceBaseMember.lead_id == Lead.id).filter(AudienceBaseMember.base_id == base.id)


def _base_counts(db: Session, base: AudienceBase) -> dict[str, int]:
    query = _base_lead_query(db, base)
    total = query.count()
    active = query.join(TelegramUser, Lead.telegram_user_id == TelegramUser.id).filter(
        TelegramUser.is_blocked.is_(False),
        TelegramUser.unsubscribed.is_(False),
    ).count()
    blocked_or_unsubscribed = query.join(TelegramUser, Lead.telegram_user_id == TelegramUser.id).filter(
        or_(TelegramUser.is_blocked.is_(True), TelegramUser.unsubscribed.is_(True))
    ).count()
    return {"total": total, "active": active, "blocked_or_unsubscribed": blocked_or_unsubscribed}


def _base_dict(db: Session, base: AudienceBase) -> dict:
    counts = _base_counts(db, base)
    last_broadcast = db.query(Broadcast).filter(Broadcast.base_id == base.id).order_by(Broadcast.created_at.desc()).first()
    return {
        "id": base.id,
        "name": base.name,
        "description": base.description,
        "type": base.type,
        "filters_json": base.filters_json or {},
        "created_by": {"id": base.created_by.id, "name": base.created_by.name, "email": base.created_by.email} if base.created_by else None,
        "created_at": base.created_at,
        "updated_at": base.updated_at,
        "members_count": counts["total"],
        "active_users": counts["active"],
        "blocked_or_unsubscribed": counts["blocked_or_unsubscribed"],
        "last_broadcast": {"id": last_broadcast.id, "title": last_broadcast.title, "status": last_broadcast.status, "created_at": last_broadcast.created_at}
        if last_broadcast
        else None,
    }


def _member_dict(lead: Lead, membership: AudienceBaseMember | None = None) -> dict:
    user = lead.telegram_user
    return {
        "lead_id": lead.id,
        "telegram_user_id": lead.telegram_user_id,
        "name": lead.name,
        "username": user.username if user else None,
        "telegram_id": user.telegram_id if user else None,
        "crm_status": lead.crm_status,
        "selected_problems": lead.selected_problems or [],
        "report_opened": lead.report_opened,
        "cta_clicked": lead.cta_clicked,
        "manager": {"id": lead.assigned_manager.id, "name": lead.assigned_manager.name, "email": lead.assigned_manager.email} if lead.assigned_manager else None,
        "tags": lead.tags or [],
        "is_blocked": user.is_blocked if user else False,
        "unsubscribed": user.unsubscribed if user else False,
        "added_at": membership.added_at if membership else None,
    }


@router.get("")
def list_bases(_: AdminAuth, db: Session = Depends(get_db), page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=100)) -> dict:
    query = db.query(AudienceBase).options(selectinload(AudienceBase.created_by)).order_by(AudienceBase.created_at.desc())
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    return {"items": [_base_dict(db, item) for item in items], "total": total, "page": page, "page_size": page_size}


@router.post("")
def create_base(payload: AudienceBaseCreate, admin: AdminAuth, db: Session = Depends(get_db)) -> dict:
    require_write_access(admin)
    name = _clean_text(payload.name)
    if not name:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Название базы обязательно")
    existing = db.query(AudienceBase).filter(func.lower(AudienceBase.name) == name.lower()).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="База с таким названием уже существует")
    base = AudienceBase(name=name, description=payload.description, type=payload.type, filters_json=payload.filters_json, created_by_id=admin.id)
    db.add(base)
    db.commit()
    db.refresh(base)
    return _base_dict(db, base)


@router.get("/{base_id}")
def get_base(
    base_id: int,
    _: AdminAuth,
    db: Session = Depends(get_db),
    search: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
) -> dict:
    base = db.query(AudienceBase).options(selectinload(AudienceBase.created_by)).filter(AudienceBase.id == base_id).first()
    if not base:
        raise not_found("База не найдена")
    query = _base_lead_query(db, base)
    if search:
        like = f"%{search.strip()}%"
        query = query.join(TelegramUser, Lead.telegram_user_id == TelegramUser.id).filter(
            or_(Lead.name.ilike(like), TelegramUser.username.ilike(like), cast(TelegramUser.telegram_id, String).ilike(like))
        )
    total = query.count()
    leads = query.order_by(Lead.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    memberships = {}
    if base.type == "static":
        memberships = {
            item.lead_id: item
            for item in db.query(AudienceBaseMember).filter(
                AudienceBaseMember.base_id == base.id,
                AudienceBaseMember.lead_id.in_([lead.id for lead in leads] or [0]),
            )
        }
    payload = _base_dict(db, base)
    payload["members"] = [_member_dict(lead, memberships.get(lead.id)) for lead in leads]
    payload["members_total"] = total
    payload["page"] = page
    payload["page_size"] = page_size
    return payload


@router.patch("/{base_id}")
def patch_base(base_id: int, payload: AudienceBasePatch, admin: AdminAuth, db: Session = Depends(get_db)) -> dict:
    require_write_access(admin)
    base = db.query(AudienceBase).filter(AudienceBase.id == base_id).first()
    if not base:
        raise not_found("База не найдена")
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        name = _clean_text(data["name"])
        if not name:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Название базы обязательно")
        existing = db.query(AudienceBase).filter(AudienceBase.id != base.id, func.lower(AudienceBase.name) == name.lower()).first()
        if existing:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="База с таким названием уже существует")
        base.name = name
    if "description" in data:
        base.description = data["description"]
    if data.get("type") is not None:
        base.type = data["type"]
    if data.get("filters_json") is not None:
        base.filters_json = data["filters_json"]
    db.commit()
    db.refresh(base)
    return _base_dict(db, base)


@router.delete("/{base_id}")
def delete_base(base_id: int, admin: AdminAuth, db: Session = Depends(get_db)) -> dict:
    require_write_access(admin)
    base = db.query(AudienceBase).filter(AudienceBase.id == base_id).first()
    if not base:
        raise not_found("База не найдена")
    db.delete(base)
    db.commit()
    return {"ok": True}


@router.post("/{base_id}/members")
def add_base_members(base_id: int, payload: AudienceBaseMembersPatch, admin: AdminAuth, db: Session = Depends(get_db)) -> dict:
    require_write_access(admin)
    base = db.query(AudienceBase).filter(AudienceBase.id == base_id).first()
    if not base:
        raise not_found("База не найдена")
    if base.type != "static":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="В dynamic segment нельзя добавлять вручную")
    query = db.query(Lead)
    clauses = []
    if payload.lead_ids:
        clauses.append(Lead.id.in_(payload.lead_ids))
    if payload.telegram_user_ids:
        clauses.append(Lead.telegram_user_id.in_(payload.telegram_user_ids))
    if not clauses:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Нужны lead_ids или telegram_user_ids")
    leads = query.filter(or_(*clauses)).all()
    added = 0
    for lead in leads:
        exists = db.query(AudienceBaseMember).filter(AudienceBaseMember.base_id == base.id, AudienceBaseMember.lead_id == lead.id).first()
        if exists:
            continue
        db.add(AudienceBaseMember(base_id=base.id, lead_id=lead.id, telegram_user_id=lead.telegram_user_id, added_by_id=admin.id))
        added += 1
    db.commit()
    return {"ok": True, "added": added}


@router.delete("/{base_id}/members/{user_id}")
def remove_base_member(base_id: int, user_id: int, admin: AdminAuth, db: Session = Depends(get_db)) -> dict:
    require_write_access(admin)
    deleted = (
        db.query(AudienceBaseMember)
        .filter(
            AudienceBaseMember.base_id == base_id,
            or_(AudienceBaseMember.lead_id == user_id, AudienceBaseMember.telegram_user_id == user_id),
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    return {"ok": True, "removed": deleted}


@router.post("/{base_id}/import")
async def import_base_csv(base_id: int, admin: AdminAuth, db: Session = Depends(get_db), file: UploadFile = File(...)) -> dict:
    require_write_access(admin)
    content = (await file.read()).decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(content))
    lead_ids: list[int] = []
    telegram_user_ids: list[int] = []
    for row in reader:
        if str(row.get("lead_id") or "").isdigit():
            lead_ids.append(int(row["lead_id"]))
        if str(row.get("telegram_user_id") or row.get("user_id") or "").isdigit():
            telegram_user_ids.append(int(row.get("telegram_user_id") or row.get("user_id")))
    return add_base_members(base_id, AudienceBaseMembersPatch(lead_ids=lead_ids, telegram_user_ids=telegram_user_ids), admin, db)


@router.get("/{base_id}/export")
def export_base_csv(base_id: int, _: AdminAuth, db: Session = Depends(get_db)) -> StreamingResponse:
    base = db.query(AudienceBase).filter(AudienceBase.id == base_id).first()
    if not base:
        raise not_found("База не найдена")
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["lead_id", "telegram_user_id", "telegram_id", "username", "name", "status", "report_opened", "cta_clicked", "tags"])
    for lead in _base_lead_query(db, base).order_by(Lead.created_at.desc()).all():
        user = lead.telegram_user
        writer.writerow(
            [
                lead.id,
                lead.telegram_user_id,
                user.telegram_id if user else "",
                user.username if user else "",
                lead.name or "",
                lead.crm_status,
                lead.report_opened,
                lead.cta_clicked,
                "; ".join(lead.tags or []),
            ]
        )
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": f"attachment; filename=base_{base_id}.csv"})
