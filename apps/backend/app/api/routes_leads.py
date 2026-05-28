import csv
import io

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import String, cast, or_
from sqlalchemy.orm import Session, selectinload

from app.api.schemas import LeadPatch
from app.api.serializers import lead_dict
from app.core.exceptions import not_found
from app.core.security import AdminAuth
from app.db.models import AnalysisRequest, Lead, TelegramUser
from app.db.session import get_db
from app.storage.local import local_storage

router = APIRouter(prefix="/api/leads", tags=["leads"])


def _analysis_storage_paths(lead: Lead) -> set[str]:
    paths: set[str] = set()
    for analysis in lead.analyses or []:
        for path in [
            analysis.original_photo_path,
            analysis.protocol_image_path,
            analysis.face_protocol_image_path,
            analysis.legacy_protocol_image_path,
            analysis.after_photo_path,
            analysis.after_photo_final_path,
        ]:
            if path:
                paths.add(path)
        for path in analysis.protocol_slide_paths or []:
            if path:
                paths.add(path)
        for path in analysis.after_photo_variant_paths or []:
            if path:
                paths.add(path)
        for image in analysis.images or []:
            if image.path:
                paths.add(image.path)
    return paths


@router.get("")
def list_leads(
    _: AdminAuth,
    db: Session = Depends(get_db),
    search: str | None = None,
    status: str | None = None,
    problem: str | None = None,
    tag: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    query = db.query(Lead).options(selectinload(Lead.telegram_user), selectinload(Lead.analyses))
    if search:
        like = f"%{search}%"
        query = query.join(TelegramUser).filter(or_(Lead.name.ilike(like), TelegramUser.username.ilike(like)))
    if status:
        query = query.filter(Lead.status == status)
    if problem:
        query = query.filter(Lead.selected_problems.contains([problem]) if db.bind.dialect.name == "postgresql" else cast(Lead.selected_problems, String).ilike(f"%{problem}%"))
    if tag:
        query = query.filter(Lead.tags.contains([tag]) if db.bind.dialect.name == "postgresql" else cast(Lead.tags, String).ilike(f"%{tag}%"))
    total = query.count()
    items = query.order_by(Lead.created_at.desc()).offset(offset).limit(limit).all()
    return {"items": [lead_dict(item) for item in items], "total": total, "limit": limit, "offset": offset}


@router.get("/export")
def export_leads(_: AdminAuth, db: Session = Depends(get_db)) -> StreamingResponse:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "name", "telegram_username", "telegram_id", "status", "problems", "report_opened", "cta_clicked", "source", "tags"])
    for lead in db.query(Lead).options(selectinload(Lead.telegram_user)).order_by(Lead.created_at.desc()).all():
        writer.writerow(
            [
                lead.id,
                lead.name or "",
                lead.telegram_user.username if lead.telegram_user else "",
                lead.telegram_user.telegram_id if lead.telegram_user else "",
                lead.status,
                "; ".join(lead.selected_problems or []),
                lead.report_opened,
                lead.cta_clicked,
                lead.source or "",
                "; ".join(lead.tags or []),
            ]
        )
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=leads.csv"})


@router.get("/{lead_id}")
def get_lead(lead_id: int, _: AdminAuth, db: Session = Depends(get_db)) -> dict:
    lead = (
        db.query(Lead)
        .options(selectinload(Lead.telegram_user), selectinload(Lead.analyses), selectinload(Lead.notes))
        .filter(Lead.id == lead_id)
        .first()
    )
    if not lead:
        raise not_found("Лид не найден")
    return lead_dict(lead, include_analyses=True)


@router.patch("/{lead_id}")
def patch_lead(lead_id: int, payload: LeadPatch, _: AdminAuth, db: Session = Depends(get_db)) -> dict:
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise not_found("Лид не найден")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(lead, field, value)
    db.commit()
    db.refresh(lead)
    return lead_dict(lead)


@router.delete("/{lead_id}")
def delete_lead(lead_id: int, _: AdminAuth, db: Session = Depends(get_db)) -> dict:
    lead = (
        db.query(Lead)
        .options(selectinload(Lead.analyses).selectinload(AnalysisRequest.images))
        .filter(Lead.id == lead_id)
        .first()
    )
    if not lead:
        raise not_found("Лид не найден")
    storage_paths = _analysis_storage_paths(lead)
    telegram_user = lead.telegram_user
    db.delete(lead)
    if telegram_user:
        db.delete(telegram_user)
    db.commit()
    for path in storage_paths:
        local_storage.delete_file(path)
    return {"ok": True}
