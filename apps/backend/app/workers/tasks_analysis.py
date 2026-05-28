from __future__ import annotations

import logging
import hashlib
import time
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.ai.openai_client import build_personal_insights_from_analysis
from app.ai.prompts import load_default_system_prompt
from app.ai.providers import analyze_face_with_fallback
from app.ai.schemas import FaceAnalysis
from app.core.config import settings
from app.db.crm import add_lead_event
from app.db.models import (
    AiJobLog,
    AnalysisRequest,
    AnalysisStatus,
    CampaignSource,
    FaceZone,
    GeneratedImage,
    GeneratedReport,
    SelectedProblem,
)
from app.db.repositories import get_bot_settings, get_prompt
from app.db.session import SessionLocal
from app.knowledge.retriever import retrieve_context
from app.reports.html_report import build_face_protocol_html, build_report_json
from app.reports.face_protocol_final.normalize import build_protocol_copy_from_analysis
from app.reports.face_zone_protocol import render_face_zone_protocol_v1
from app.storage.local import local_storage
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)
FACE_PROTOCOL_WIDTH = 1600
FACE_PROTOCOL_HEIGHT = 1200
FACE_ZONE_PROTOCOL_WIDTH = 1184
FACE_ZONE_PROTOCOL_HEIGHT = 1980

AFTER_PHOTO_READY_STATUSES = {"APPROVED", "COMPLETED"}
AFTER_PHOTO_TERMINAL_STATUSES = {
    "APPROVED",
    "COMPLETED",
    "FAILED",
    "SKIPPED_NO_API_KEY",
    "NEEDS_MANUAL_REVIEW",
}


def _enqueue_progress_update(analysis_id: int, stage: str) -> None:
    try:
        from app.workers.tasks_telegram import enqueue_analysis_progress_update

        enqueue_analysis_progress_update(analysis_id, stage)
    except Exception:
        logger.warning("Could not enqueue Telegram progress update", exc_info=True)


def log_job(db: Session, analysis_id: int | None, stage: str, status: str, message: str | None = None, payload: dict | None = None) -> None:
    db.add(AiJobLog(analysis_id=analysis_id, stage=stage, status=status, message=message, payload=payload or {}))
    db.commit()


def _has_successful_telegram_send(db: Session, analysis_id: int) -> bool:
    return (
        db.query(AiJobLog.id)
        .filter(
            AiJobLog.analysis_id == analysis_id,
            AiJobLog.stage == "telegram_send",
            AiJobLog.status == "success",
        )
        .first()
        is not None
    )


def _set_status(db: Session, analysis: AnalysisRequest, status: str) -> None:
    analysis.status = status
    if analysis.lead:
        analysis.lead.status = status
    if analysis.telegram_user:
        analysis.telegram_user.current_status = status
    db.commit()


def _sync_selected_problem_rows(db: Session, analysis: AnalysisRequest) -> None:
    db.query(SelectedProblem).filter(SelectedProblem.analysis_id == analysis.id).delete()
    for problem in analysis.selected_problems or []:
        db.add(SelectedProblem(analysis_id=analysis.id, slug=problem, title=problem))


def _persist_zones(db: Session, analysis: AnalysisRequest, zones: list[dict]) -> None:
    db.query(FaceZone).filter(FaceZone.analysis_id == analysis.id).delete()
    for zone in zones:
        db.add(
            FaceZone(
                analysis_id=analysis.id,
                number=zone.get("number", 0),
                name=zone.get("name", ""),
                status=zone.get("status", "attention"),
                color=zone.get("color", "yellow"),
                short_comment=zone.get("short_comment", ""),
                reason=zone.get("reason", ""),
                recommended_focus=zone.get("recommended_focus", ""),
            )
        )


def _relative_storage_path(abs_path: str) -> str:
    return Path(abs_path).resolve().relative_to(local_storage.root).as_posix()


def _photo_hash(abs_path: str) -> str:
    digest = hashlib.sha256()
    with open(abs_path, "rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()[:20]


def _sync_face_protocol_image_row(db: Session, analysis: AnalysisRequest, abs_path: str) -> None:
    db.query(GeneratedImage).filter(GeneratedImage.analysis_id == analysis.id, GeneratedImage.kind == "face_protocol_final").delete()
    db.add(
        GeneratedImage(
            analysis_id=analysis.id,
            kind="face_protocol_final",
            path=_relative_storage_path(abs_path),
            status="completed",
            metadata_json={
                "renderer": "face_zone_protocol",
                "protocol_version": "bella_face_protocol_v4",
                "output_size": f"{FACE_ZONE_PROTOCOL_WIDTH}x{FACE_ZONE_PROTOCOL_HEIGHT}",
                "first_protocol_disabled": True,
            },
        )
    )


def _sync_face_zone_protocol_image_row(db: Session, analysis: AnalysisRequest, abs_path: str) -> None:
    db.query(GeneratedImage).filter(GeneratedImage.analysis_id == analysis.id, GeneratedImage.kind == "face_zone_protocol").delete()
    db.add(
        GeneratedImage(
            analysis_id=analysis.id,
            kind="face_zone_protocol",
            path=_relative_storage_path(abs_path),
            status="completed",
            metadata_json={
                "renderer": "face_zone_protocol",
                "protocol_version": "bella_face_protocol_v4",
                "uses_mediapipe": True,
            },
        )
    )


def regenerate_personal_insights_sync(db: Session, analysis: AnalysisRequest) -> dict:
    if not analysis.analysis_json:
        raise ValueError("У анализа нет analysis_json")
    personal_insight_json = build_personal_insights_from_analysis(analysis.analysis_json, analysis.selected_problems or [])
    analysis.personal_insight_json = personal_insight_json
    db.commit()
    log_job(db, analysis.id, "personal_insights", "success", "Personal insight JSON built locally")
    return personal_insight_json


def regenerate_protocol_copy_sync(db: Session, analysis: AnalysisRequest) -> dict:
    if not analysis.analysis_json:
        raise ValueError("У анализа нет analysis_json")
    personal_insight_json = regenerate_personal_insights_sync(db, analysis)
    user_age = analysis.lead.age if analysis.lead else None
    protocol_copy_json = build_protocol_copy_from_analysis(analysis.analysis_json, analysis.selected_problems or [], personal_insight_json, user_age=user_age)
    analysis.protocol_copy_json = protocol_copy_json
    analysis.face_protocol_version = "final_v1"
    analysis.protocol_version = "final_v1"
    db.commit()
    log_job(db, analysis.id, "protocol_copy", "success", "Protocol copy JSON built locally")
    return protocol_copy_json


def regenerate_face_protocol_png_sync(db: Session, analysis: AnalysisRequest) -> str:
    if not analysis.original_photo_path:
        raise ValueError("У анализа нет исходного фото")
    protocol_copy_json = analysis.protocol_copy_json or regenerate_protocol_copy_sync(db, analysis)
    photo_abs = local_storage.abs_path(analysis.original_photo_path)
    protocol_dir_rel = f"protocols/final_v1/{analysis.id}"
    protocol_dir_abs = local_storage.abs_path(protocol_dir_rel)
    zone_png_abs = render_face_zone_protocol_v1(
        analysis_request_id=str(analysis.id),
        user_name=analysis.lead.name if analysis.lead else "Гость",
        user_photo_path_or_url=photo_abs,
        analysis_json=analysis.analysis_json,
        protocol_copy=protocol_copy_json,
        personal_insight_json=analysis.personal_insight_json,
        output_dir=protocol_dir_abs,
        created_at=analysis.created_at,
    )
    if not Path(zone_png_abs).exists():
        raise RuntimeError("Expected face zone protocol PNG was not generated")
    relative_zone_png = _relative_storage_path(zone_png_abs)
    analysis.face_protocol_version = "final_v1"
    analysis.face_protocol_image_path = relative_zone_png
    analysis.protocol_version = "final_v1"
    analysis.protocol_image_path = relative_zone_png
    analysis.protocol_image_url = None
    analysis.legacy_protocol_image_url = None
    analysis.protocol_slide_paths = []
    analysis.protocol_slide_copy = {}
    _sync_face_protocol_image_row(db, analysis, zone_png_abs)
    _sync_face_zone_protocol_image_row(db, analysis, zone_png_abs)
    db.commit()
    logger.info("First face protocol PNG generation disabled; using zone protocol as main PNG")
    logger.info("Saved face zone protocol PNG: %s", zone_png_abs)
    log_job(
        db,
        analysis.id,
        "face_protocol_final_v1",
        "skipped",
        "First protocol generation disabled; journal zone protocol is used as main protocol",
        {
            "renderer": "face_zone_protocol",
            "protocol_version": "final_v1",
            "path": relative_zone_png,
            "outputSize": f"{FACE_ZONE_PROTOCOL_WIDTH}x{FACE_ZONE_PROTOCOL_HEIGHT}",
            "firstProtocolDisabled": True,
        },
    )
    log_job(
        db,
        analysis.id,
        "face_zone_protocol_v1",
        "success",
        relative_zone_png,
        {
            "renderer": "face_zone_protocol",
            "protocol_version": "bella_face_protocol_v4",
            "usesMediaPipe": True,
            "path": relative_zone_png,
        },
    )
    return zone_png_abs


def _wait_for_after_photo_for_protocol(db: Session, analysis: AnalysisRequest, *, started: bool) -> dict:
    if not started:
        return {"waited": False, "reason": "not_started", "status": analysis.after_photo_status}

    _enqueue_progress_update(analysis.id, "after_photo")
    timeout_seconds = max(1, int(settings.after_photo_timeout_seconds or 300))
    poll_interval = 2.0
    wait_started = time.perf_counter()
    log_job(
        db,
        analysis.id,
        "after_photo_wait",
        "started",
        "Waiting for after-photo before rendering photo protocol",
        {"timeoutSeconds": timeout_seconds},
    )

    while True:
        db.refresh(analysis)
        status = analysis.after_photo_status
        if status in AFTER_PHOTO_READY_STATUSES and analysis.after_photo_final_path:
            final_abs = local_storage.abs_path(analysis.after_photo_final_path)
            if Path(final_abs).exists():
                waited_ms = int((time.perf_counter() - wait_started) * 1000)
                result = {
                    "waited": True,
                    "status": status,
                    "afterPhotoPath": analysis.after_photo_final_path,
                    "waitTimeMs": waited_ms,
                    "embedded": True,
                }
                log_job(db, analysis.id, "after_photo_wait", "success", "After-photo ready for embedded protocol", result)
                return result
            log_job(
                db,
                analysis.id,
                "after_photo_wait",
                "failed",
                "Approved after-photo file was not found before protocol render",
                {"status": status, "afterPhotoPath": analysis.after_photo_final_path},
            )
            return {"waited": True, "status": status, "embedded": False, "reason": "file_missing"}

        if status in AFTER_PHOTO_TERMINAL_STATUSES:
            waited_ms = int((time.perf_counter() - wait_started) * 1000)
            result = {"waited": True, "status": status, "waitTimeMs": waited_ms, "embedded": False}
            log_job(db, analysis.id, "after_photo_wait", "terminal_without_image", "After-photo finished without approved image", result)
            return result

        elapsed = time.perf_counter() - wait_started
        if elapsed >= timeout_seconds:
            result = {
                "waited": True,
                "status": status or "PENDING",
                "waitTimeMs": int(elapsed * 1000),
                "embedded": False,
                "reason": "timeout",
            }
            log_job(db, analysis.id, "after_photo_wait", "timeout", "After-photo was not ready before protocol render", result)
            return result

        time.sleep(poll_interval)


def _run_analysis_pipeline(analysis_id: int) -> None:
    db = SessionLocal()
    analysis: AnalysisRequest | None = None
    total_started = time.perf_counter()
    analysis_provider = None
    analysis_time_ms = 0
    report_build_time_ms = 0
    telegram_send_time_ms = 0
    after_photo_started = False
    try:
        analysis = db.query(AnalysisRequest).filter(AnalysisRequest.id == analysis_id).first()
        if not analysis:
            return
        if not analysis.original_photo_path:
            raise ValueError("У анализа нет исходного фото")
        if analysis.status == AnalysisStatus.COMPLETED and analysis.report and analysis.face_protocol_image_path:
            report_url = f"{settings.public_app_url.rstrip('/')}/report/{analysis.report.public_token}"
            if _has_successful_telegram_send(db, analysis.id):
                log_job(
                    db,
                    analysis.id,
                    "pipeline",
                    "skipped",
                    "Analysis already completed and protocol already sent; duplicate Celery retry ignored",
                    {"reason": "duplicate_completed_analysis"},
                )
                return
            if analysis.telegram_user:
                from app.workers.tasks_telegram import enqueue_analysis_ready_message

                log_job(
                    db,
                    analysis.id,
                    "pipeline",
                    "skipped",
                    "Analysis already completed; queued missing Telegram delivery without reprocessing AI",
                    {"reason": "completed_without_telegram_send"},
                )
                enqueue_analysis_ready_message(analysis.id, report_url)
                return

        bot_settings = get_bot_settings(db)
        log_job(
            db,
            analysis.id,
            "pipeline",
            "started",
            "Hybrid AI pipeline started",
            {
                "analysisProvider": settings.ai_text_provider,
                "imageProvider": settings.ai_image_provider,
                "experimentMode": settings.ai_experiment_mode,
            },
        )
        _set_status(db, analysis, AnalysisStatus.ANALYZING)
        _enqueue_progress_update(analysis.id, "analysis")

        photo_abs = local_storage.abs_path(analysis.original_photo_path)
        if bot_settings.after_photo_enabled and settings.enable_after_photo:
            from app.workers.tasks_after_photo import enqueue_after_photo

            enqueue_after_photo(analysis.id, run_sync_fallback=False)
            after_photo_started = True

        knowledge_context = retrieve_context(db, analysis.selected_problems or [])
        system_prompt = get_prompt(db, "analysis_system", load_default_system_prompt())
        analysis_result = analyze_face_with_fallback(
            photo_abs,
            analysis.lead.name if analysis.lead else None,
            analysis.selected_problems or [],
            knowledge_context,
            system_prompt,
            user_age=analysis.lead.age if analysis.lead else None,
        )
        analysis_provider = analysis_result.provider
        analysis_time_ms = analysis_result.latency_ms
        validation_meta = analysis_result.payload.get("_validation_meta") if isinstance(analysis_result.payload, dict) else {}
        validation_meta = validation_meta if isinstance(validation_meta, dict) else {}
        bella_protocol = analysis_result.payload.get("bella_protocol") if isinstance(analysis_result.payload, dict) else None
        bella_protocol_v4 = analysis_result.payload.get("bella_protocol_v4") if isinstance(analysis_result.payload, dict) else None
        strict_blocks = analysis_result.payload.get("strict_blocks") if isinstance(analysis_result.payload, dict) else None
        analysis_context = analysis_result.payload.get("analysis_context") if isinstance(analysis_result.payload, dict) else None
        validated = FaceAnalysis.model_validate(analysis_result.payload).model_dump()
        if bella_protocol:
            validated["bella_protocol"] = bella_protocol
        if bella_protocol_v4:
            validated["bella_protocol_v4"] = bella_protocol_v4
        if strict_blocks:
            validated["strict_blocks"] = strict_blocks
        if analysis_context:
            validated["analysis_context"] = analysis_context
        if validation_meta:
            validated["_validation_meta"] = validation_meta
        analysis.analysis_json = validated
        _sync_selected_problem_rows(db, analysis)
        _persist_zones(db, analysis, validated.get("zones", []))
        db.commit()
        log_job(
            db,
            analysis.id,
            "face_analysis",
            "success",
            "Structured JSON analysis saved",
            {
                "provider": analysis_provider,
                "latencyMs": analysis_time_ms,
                "fallbackUsed": analysis_result.fallback_used or bool(validation_meta.get("fallbackUsed")),
                "mockMode": settings.ai_mock_mode,
                "userId": analysis.telegram_user.telegram_id if analysis.telegram_user else None,
                "photoHash": _photo_hash(photo_abs),
                "clientAge": analysis.lead.age if analysis.lead else None,
                "visualAge": (analysis_context or {}).get("visual_age") if isinstance(analysis_context, dict) else None,
                "selectedAgingType": (analysis_context or {}).get("aging_type_id") if isinstance(analysis_context, dict) else None,
                "validationPassed": validation_meta.get("validationPassed", True),
                "retryCount": validation_meta.get("retryCount", 0),
                "validationErrors": validation_meta.get("validationErrors", []),
            },
        )

        _set_status(db, analysis, AnalysisStatus.GENERATING_PROTOCOL)
        _enqueue_progress_update(analysis.id, "protocol_copy")
        logger.info("FACE_PROTOCOL_RENDERER=journal_v1")
        try:
            personal_insight_json = build_personal_insights_from_analysis(validated, analysis.selected_problems or [])
            analysis.personal_insight_json = personal_insight_json
            _user_age = analysis.lead.age if analysis.lead else None
            protocol_copy_json = build_protocol_copy_from_analysis(validated, analysis.selected_problems or [], personal_insight_json, user_age=_user_age)
            analysis.protocol_copy_json = protocol_copy_json
            analysis.face_protocol_version = "final_v1"
            analysis.protocol_version = "final_v1"
            db.commit()
            log_job(db, analysis.id, "protocol_copy", "success", "Protocol copy JSON built locally", {"source": "backend_template"})
            after_photo_wait_result = {
                "waited": False,
                "embedded": False,
                "reason": "first_protocol_disabled",
                "status": analysis.after_photo_status,
            }
            _enqueue_progress_update(analysis.id, "render")
            protocol_png_abs = regenerate_face_protocol_png_sync(db, analysis)
            log_job(
                db,
                analysis.id,
                "face_zone_protocol_v1",
                "rendered_without_after_photo",
                "Journal zone protocol rendered; first protocol generation is disabled",
                after_photo_wait_result,
            )
        except Exception as exc:
            logger.error("Face protocol render failed", exc_info=True)
            analysis.status = AnalysisStatus.FAILED_PROTOCOL_RENDER
            analysis.error_message = str(exc)
            if analysis.lead:
                analysis.lead.status = AnalysisStatus.FAILED_PROTOCOL_RENDER
            if analysis.telegram_user:
                analysis.telegram_user.current_status = AnalysisStatus.FAILED_PROTOCOL_RENDER
            db.commit()
            log_job(db, analysis.id, "face_protocol_final_v1", "failed", str(exc))
            raise

        _set_status(db, analysis, AnalysisStatus.GENERATING_REPORT)
        _enqueue_progress_update(analysis.id, "report")
        report_started = time.perf_counter()
        report_extra = {
            "source": "backend_template",
            "provider": analysis_provider,
            "offer_angle": validated.get("cta_recommendation"),
        }
        report_json = build_report_json(analysis.lead.name if analysis.lead else "Гость", validated, analysis.selected_problems or [], report_extra)
        html = build_face_protocol_html(validated, analysis.lead.name if analysis.lead else "Гость", analysis.selected_problems or [], report_extra)
        report_build_time_ms = int((time.perf_counter() - report_started) * 1000)
        report = analysis.report or GeneratedReport(analysis_id=analysis.id, lead_id=analysis.lead_id)
        report.report_json = report_json
        report.html_content = html
        report.is_published = True
        db.add(report)
        analysis.report_json = report_json
        db.commit()
        db.refresh(report)
        if analysis.telegram_user and analysis.telegram_user.campaign:
            campaign: CampaignSource = analysis.telegram_user.campaign
            campaign.report_count += 1
        log_job(db, analysis.id, "report", "success", f"Public token: {report.public_token}", {"buildTimeMs": report_build_time_ms, "source": "backend_template"})

        if bot_settings.manual_moderation_enabled:
            _set_status(db, analysis, AnalysisStatus.NEEDS_REVIEW)
        else:
            analysis.status = AnalysisStatus.COMPLETED
            analysis.completed_at = datetime.now(timezone.utc)
            if analysis.lead:
                analysis.lead.status = AnalysisStatus.COMPLETED
                add_lead_event(db, analysis.lead, "scenario_completed", "Пользователь прошел face-протокол", {"analysis_id": analysis.id})
            if analysis.telegram_user:
                analysis.telegram_user.current_status = AnalysisStatus.COMPLETED
            db.commit()

        if not bot_settings.manual_moderation_enabled and analysis.telegram_user:
            report_url = f"{settings.public_app_url.rstrip('/')}/report/{report.public_token}"
            _enqueue_progress_update(analysis.id, "almost_ready")
            if analysis.face_protocol_version != "final_v1":
                raise RuntimeError("Expected final_v1 face protocol for new analysis")
            if not analysis.face_protocol_image_path:
                analysis.status = AnalysisStatus.FAILED_PROTOCOL_RENDER
                analysis.error_message = "Expected final_v1 PNG path was empty"
                db.commit()
                raise RuntimeError("Expected final_v1 PNG path was empty")
            protocol_png_abs = local_storage.abs_path(analysis.face_protocol_image_path)
            if not Path(protocol_png_abs).exists():
                logger.error("Face protocol PNG missing: %s", protocol_png_abs)
                analysis.status = AnalysisStatus.FAILED_PROTOCOL_RENDER
                analysis.error_message = "Expected final_v1 PNG was not found"
                if analysis.lead:
                    analysis.lead.status = AnalysisStatus.FAILED_PROTOCOL_RENDER
                if analysis.telegram_user:
                    analysis.telegram_user.current_status = AnalysisStatus.FAILED_PROTOCOL_RENDER
                db.commit()
                log_job(db, analysis.id, "telegram_send", "failed", "Expected final_v1 PNG was not found")
                raise RuntimeError("Expected final_v1 PNG was not found")
            from app.workers.tasks_telegram import enqueue_analysis_ready_message

            telegram_started = time.perf_counter()
            if _has_successful_telegram_send(db, analysis.id):
                log_job(
                    db,
                    analysis.id,
                    "telegram_send",
                    "skipped",
                    "Protocol already sent; duplicate enqueue ignored",
                    {"reason": "duplicate_pipeline_retry"},
                )
            else:
                enqueue_analysis_ready_message(analysis.id, report_url)
            telegram_send_time_ms = int((time.perf_counter() - telegram_started) * 1000)

        total_ms = int((time.perf_counter() - total_started) * 1000)
        log_job(db, analysis.id, "pipeline", "success", "Hybrid AI pipeline completed")
        log_job(
            db,
            analysis.id,
            "ai_processing_performance",
            "success",
            "Hybrid AI processing latency",
            {
                "totalProcessingTimeMs": total_ms,
                "analysisProvider": analysis_provider,
                "analysisTimeMs": analysis_time_ms,
                "imageProvider": settings.ai_image_provider,
                "imageTimeMs": None,
                "afterPhotoStarted": after_photo_started,
                "reportBuildTimeMs": report_build_time_ms,
                "telegramSendTimeMs": telegram_send_time_ms,
                "success": True,
                "errorMessage": None,
                "userId": analysis.telegram_user.telegram_id if analysis.telegram_user else None,
                "jobId": analysis.id,
                "experimentMode": settings.ai_experiment_mode,
            },
        )
    except Exception as exc:
        logger.exception("Analysis pipeline failed")
        analysis = db.query(AnalysisRequest).filter(AnalysisRequest.id == analysis_id).first()
        if analysis:
            if analysis.status != AnalysisStatus.FAILED_PROTOCOL_RENDER:
                analysis.status = AnalysisStatus.FAILED
            analysis.error_message = str(exc)
            if analysis.lead:
                analysis.lead.status = analysis.status
            if analysis.telegram_user:
                analysis.telegram_user.current_status = analysis.status
            db.commit()
        total_ms = int((time.perf_counter() - total_started) * 1000)
        log_job(db, analysis_id, "pipeline", "failed", str(exc))
        log_job(
            db,
            analysis_id,
            "ai_processing_performance",
            "failed",
            str(exc),
            {
                "totalProcessingTimeMs": total_ms,
                "analysisProvider": analysis_provider or settings.ai_text_provider,
                "analysisTimeMs": analysis_time_ms,
                "imageProvider": settings.ai_image_provider,
                "imageTimeMs": None,
                "afterPhotoStarted": after_photo_started,
                "reportBuildTimeMs": report_build_time_ms,
                "telegramSendTimeMs": telegram_send_time_ms,
                "success": False,
                "errorMessage": str(exc),
                "userId": analysis.telegram_user.telegram_id if analysis and analysis.telegram_user else None,
                "jobId": analysis_id,
                "experimentMode": settings.ai_experiment_mode,
            },
        )
        raise
    finally:
        db.close()


@celery_app.task(
    name="app.workers.tasks_analysis.run_analysis_pipeline",
    bind=True,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": settings.ai_retry_count},
    retry_backoff=True,
)
def run_analysis_pipeline(self, analysis_id: int) -> None:
    _run_analysis_pipeline(analysis_id)


def enqueue_analysis(analysis_id: int) -> None:
    try:
        run_analysis_pipeline.apply_async(args=[analysis_id], queue="analysis")
    except Exception:
        logger.warning("Celery broker unavailable, running analysis synchronously in current process")
        _run_analysis_pipeline(analysis_id)
