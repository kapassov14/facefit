from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session, selectinload

from app.api.schemas import ReviewPatch
from app.api.serializers import analysis_dict
from app.core.config import AFTER_PHOTO_DISABLED_REASON
from app.core.exceptions import not_found
from app.core.security import AdminAuth
from app.db.models import AnalysisRequest, AnalysisStatus
from app.db.session import get_db
from app.workers.tasks_analysis import (
    enqueue_analysis,
    regenerate_face_protocol_png_sync,
    regenerate_personal_insights_sync,
    regenerate_protocol_copy_sync,
)
from app.workers.tasks_report import enqueue_report

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


def _after_photo_disabled_response() -> dict:
    return {"ok": False, "status": "DISABLED", "message": AFTER_PHOTO_DISABLED_REASON}


@router.get("")
def list_analysis(
    _: AdminAuth,
    db: Session = Depends(get_db),
    status: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
) -> dict:
    query = db.query(AnalysisRequest).options(selectinload(AnalysisRequest.lead), selectinload(AnalysisRequest.report))
    if status:
        query = query.filter(AnalysisRequest.status == status)
    total = query.count()
    items = query.order_by(AnalysisRequest.created_at.desc()).offset(offset).limit(limit).all()
    return {"items": [analysis_dict(item, compact=True) for item in items], "total": total, "limit": limit, "offset": offset}


@router.get("/{analysis_id}")
def get_analysis(analysis_id: int, _: AdminAuth, db: Session = Depends(get_db)) -> dict:
    analysis = (
        db.query(AnalysisRequest)
        .options(
            selectinload(AnalysisRequest.lead),
            selectinload(AnalysisRequest.telegram_user),
            selectinload(AnalysisRequest.report),
            selectinload(AnalysisRequest.zones),
            selectinload(AnalysisRequest.ai_logs),
            selectinload(AnalysisRequest.images),
        )
        .filter(AnalysisRequest.id == analysis_id)
        .first()
    )
    if not analysis:
        raise not_found("Анализ не найден")
    return analysis_dict(analysis)


@router.post("/{analysis_id}/retry")
def retry_analysis(analysis_id: int, _: AdminAuth, db: Session = Depends(get_db)) -> dict:
    analysis = db.query(AnalysisRequest).filter(AnalysisRequest.id == analysis_id).first()
    if not analysis:
        raise not_found("Анализ не найден")
    analysis.status = AnalysisStatus.QUEUED
    analysis.error_message = None
    db.commit()
    enqueue_analysis(analysis_id)
    return {"ok": True, "status": AnalysisStatus.QUEUED}


@router.post("/{analysis_id}/regenerate-report")
def regenerate_report(analysis_id: int, _: AdminAuth, db: Session = Depends(get_db)) -> dict:
    if not db.query(AnalysisRequest.id).filter(AnalysisRequest.id == analysis_id).first():
        raise not_found("Анализ не найден")
    enqueue_report(analysis_id)
    return {"ok": True}


@router.post("/{analysis_id}/regenerate-protocol-copy")
def regenerate_protocol_copy(analysis_id: int, _: AdminAuth, db: Session = Depends(get_db)) -> dict:
    analysis = db.query(AnalysisRequest).filter(AnalysisRequest.id == analysis_id).first()
    if not analysis:
        raise not_found("Анализ не найден")
    regenerate_protocol_copy_sync(db, analysis)
    return {"ok": True}


@router.post("/{analysis_id}/regenerate-personal-insights")
def regenerate_personal_insights(analysis_id: int, _: AdminAuth, db: Session = Depends(get_db)) -> dict:
    analysis = db.query(AnalysisRequest).filter(AnalysisRequest.id == analysis_id).first()
    if not analysis:
        raise not_found("Анализ не найден")
    regenerate_personal_insights_sync(db, analysis)
    return {"ok": True}


@router.post("/{analysis_id}/regenerate-face-protocol")
def regenerate_face_protocol(analysis_id: int, _: AdminAuth, db: Session = Depends(get_db)) -> dict:
    analysis = db.query(AnalysisRequest).filter(AnalysisRequest.id == analysis_id).first()
    if not analysis:
        raise not_found("Анализ не найден")
    regenerate_face_protocol_png_sync(db, analysis)
    return {"ok": True}


@router.post("/{analysis_id}/regenerate-after-photo")
def regenerate_after_photo(
    analysis_id: int,
    _: AdminAuth,
    db: Session = Depends(get_db),
    intensity: str | None = Query(None),
) -> dict:
    if not db.query(AnalysisRequest.id).filter(AnalysisRequest.id == analysis_id).first():
        raise not_found("Анализ не найден")
    return _after_photo_disabled_response()


@router.post("/{analysis_id}/regenerate-after-photo/{intensity}")
def regenerate_after_photo_with_intensity(analysis_id: int, intensity: str, _: AdminAuth, db: Session = Depends(get_db)) -> dict:
    if intensity not in {"subtle", "balanced", "visible"}:
        raise not_found("Intensity preset не найден")
    if not db.query(AnalysisRequest.id).filter(AnalysisRequest.id == analysis_id).first():
        raise not_found("Анализ не найден")
    return _after_photo_disabled_response()


@router.post("/{analysis_id}/after-photo/approve-variant")
def approve_after_photo_variant(
    analysis_id: int,
    _: AdminAuth,
    db: Session = Depends(get_db),
) -> dict:
    if not db.query(AnalysisRequest.id).filter(AnalysisRequest.id == analysis_id).first():
        raise not_found("Анализ не найден")
    return _after_photo_disabled_response()


@router.post("/{analysis_id}/after-photo/needs-manual-review")
def mark_after_photo_needs_manual_review(analysis_id: int, _: AdminAuth, db: Session = Depends(get_db)) -> dict:
    if not db.query(AnalysisRequest.id).filter(AnalysisRequest.id == analysis_id).first():
        raise not_found("Анализ не найден")
    return _after_photo_disabled_response()


@router.patch("/{analysis_id}/review")
def review_analysis(analysis_id: int, payload: ReviewPatch, _: AdminAuth, db: Session = Depends(get_db)) -> dict:
    analysis = db.query(AnalysisRequest).filter(AnalysisRequest.id == analysis_id).first()
    if not analysis:
        raise not_found("Анализ не найден")
    data = payload.model_dump(exclude_unset=True)
    if "moderation_status" in data and data["moderation_status"] is not None:
        analysis.moderation_status = data["moderation_status"]
    if "report_json" in data and data["report_json"] is not None:
        analysis.report_json = data["report_json"]
        if analysis.report:
            analysis.report.report_json = data["report_json"]
    if "status" in data and data["status"] is not None:
        analysis.status = data["status"]
    db.commit()
    db.refresh(analysis)
    return analysis_dict(analysis)
