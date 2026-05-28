from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.security import AdminAuth
from app.db.models import AiJobLog
from app.db.session import get_db

router = APIRouter(prefix="/api/admin/ai-performance", tags=["admin-ai-performance"])


def _avg(values: list[int | float | None]) -> float:
    clean = [float(value) for value in values if value is not None]
    return round(sum(clean) / len(clean), 2) if clean else 0


def _row_payload(log: AiJobLog) -> dict[str, Any]:
    payload = log.payload or {}
    return {
        "id": log.id,
        "analysis_id": log.analysis_id,
        "stage": log.stage,
        "status": log.status,
        "message": log.message,
        "created_at": log.created_at,
        "provider": payload.get("analysisProvider") or payload.get("imageProvider") or payload.get("provider"),
        "analysis_provider": payload.get("analysisProvider"),
        "image_provider": payload.get("imageProvider"),
        "analysis_time_ms": payload.get("analysisTimeMs") or payload.get("latencyMs"),
        "image_time_ms": payload.get("imageTimeMs"),
        "report_build_time_ms": payload.get("reportBuildTimeMs"),
        "telegram_send_time_ms": payload.get("telegramSendTimeMs"),
        "total_processing_time_ms": payload.get("totalProcessingTimeMs"),
        "success": payload.get("success", log.status == "success"),
        "error_message": payload.get("errorMessage") or log.message,
        "experiment_mode": payload.get("experimentMode"),
        "user_id": payload.get("userId"),
        "job_id": payload.get("jobId") or log.analysis_id,
    }


@router.get("")
def ai_performance(_: AdminAuth, db: Session = Depends(get_db), limit: int = Query(100, le=500)) -> dict:
    logs = (
        db.query(AiJobLog)
        .filter(AiJobLog.stage.in_(["ai_processing_performance", "ai_image_performance", "telegram_send", "telegram_after_photo", "face_analysis"]))
        .order_by(AiJobLog.created_at.desc())
        .limit(limit)
        .all()
    )
    rows = [_row_payload(log) for log in logs]
    by_provider: dict[str, dict[str, Any]] = defaultdict(lambda: {"count": 0, "errors": 0, "analysis": [], "image": [], "total": []})
    for row in rows:
        for provider_key, time_key in [("analysis_provider", "analysis_time_ms"), ("image_provider", "image_time_ms")]:
            provider = row.get(provider_key)
            if not provider:
                continue
            bucket = by_provider[provider]
            bucket["count"] += 1
            if row.get("success") is False:
                bucket["errors"] += 1
            if time_key == "analysis_time_ms":
                bucket["analysis"].append(row.get(time_key))
            else:
                bucket["image"].append(row.get(time_key))
            bucket["total"].append(row.get("total_processing_time_ms"))
    return {
        "summary": [
            {
                "provider": provider,
                "count": values["count"],
                "errors": values["errors"],
                "avg_analysis_time_ms": _avg(values["analysis"]),
                "avg_image_time_ms": _avg(values["image"]),
                "avg_total_processing_time_ms": _avg(values["total"]),
            }
            for provider, values in by_provider.items()
        ],
        "items": rows,
    }
