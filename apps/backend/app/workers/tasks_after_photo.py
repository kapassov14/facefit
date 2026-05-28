from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from app.after_photo.prompt_builder import build_after_photo_prompt
from app.core.config import AFTER_PHOTO_DISABLED_REASON, after_photo_feature_enabled, settings
from app.ai.providers import choose_image_provider_for_user, generate_after_photo_with_fallback
from app.db.models import AnalysisRequest, BotSettings, GeneratedImage
from app.db.session import SessionLocal
from app.storage.local import local_storage
from app.workers.celery_app import celery_app
from app.workers.tasks_analysis import log_job

logger = logging.getLogger(__name__)

AFTER_PHOTO_PROCESSING = "PROCESSING"
AFTER_PHOTO_APPROVED = "APPROVED"
AFTER_PHOTO_NEEDS_MANUAL_REVIEW = "NEEDS_MANUAL_REVIEW"
AFTER_PHOTO_FAILED = "FAILED"
AFTER_PHOTO_SKIPPED_NO_API_KEY = "SKIPPED_NO_API_KEY"
AFTER_PHOTO_PIPELINE = "structured_face_crop_qa_v1"
AFTER_PHOTO_PROMPT_SOURCE = "analysis_zone_prompt_v1"


def _mark_after_photo_disabled(db, analysis: AnalysisRequest) -> None:
    analysis.after_photo_status = "DISABLED"
    analysis.after_photo_path = None
    analysis.after_photo_final_path = None
    analysis.after_photo_variant_paths = []
    analysis.after_photo_variants = []
    analysis.after_photo_quality_results = []
    analysis.after_photo_used_intensity = None
    analysis.after_photo_retry_count = 0
    analysis.after_photo_plan = {"disabled": True, "reason": AFTER_PHOTO_DISABLED_REASON}
    image = (
        db.query(GeneratedImage)
        .filter(GeneratedImage.analysis_id == analysis.id, GeneratedImage.kind == "after_photo")
        .order_by(GeneratedImage.id.desc())
        .first()
    )
    if image:
        image.status = "disabled"
        image.path = None
        image.metadata_json = {"disabled": True, "reason": AFTER_PHOTO_DISABLED_REASON}
    log_job(db, analysis.id, "after_photo", "skipped", AFTER_PHOTO_DISABLED_REASON)


def _preferred_intensity(db, explicit_intensity: str | None) -> str:
    if explicit_intensity in {"subtle", "balanced", "visible"}:
        return explicit_intensity
    bot_settings = db.query(BotSettings).first()
    ai_settings = bot_settings.ai_settings if bot_settings and isinstance(bot_settings.ai_settings, dict) else {}
    configured = ai_settings.get("after_photo_default_intensity") or settings.after_photo_default_intensity
    return configured if configured in {"subtle", "balanced", "visible"} else "balanced"


def _wait_for_analysis_json(db, analysis: AnalysisRequest) -> dict[str, Any]:
    if analysis.analysis_json:
        return analysis.analysis_json

    timeout_seconds = max(30, min(int(settings.after_photo_timeout_seconds or 300), int(settings.ai_timeout_seconds or 180) + 60))
    poll_interval = 2.0
    started = time.perf_counter()
    log_job(
        db,
        analysis.id,
        "after_photo_analysis_wait",
        "started",
        "Waiting for analysis_json before structured after-photo prompt",
        {"timeoutSeconds": timeout_seconds},
    )
    while time.perf_counter() - started < timeout_seconds:
        time.sleep(poll_interval)
        db.refresh(analysis)
        if analysis.analysis_json:
            waited_ms = int((time.perf_counter() - started) * 1000)
            log_job(
                db,
                analysis.id,
                "after_photo_analysis_wait",
                "success",
                "analysis_json ready for after-photo prompt",
                {"waitTimeMs": waited_ms},
            )
            return analysis.analysis_json

    waited_ms = int((time.perf_counter() - started) * 1000)
    log_job(
        db,
        analysis.id,
        "after_photo_analysis_wait",
        "timeout",
        "analysis_json was not ready; using universal after-photo prompt fallback",
        {"waitTimeMs": waited_ms},
    )
    return analysis.analysis_json or {}


def _persist_result(db, analysis: AnalysisRequest, result: dict, prompt_payload: dict) -> None:
    variant_paths = result.get("variant_paths") or []
    quality_results = result.get("quality_results") or []
    final_path = result.get("final_path")
    status = result.get("status") or AFTER_PHOTO_FAILED

    provider = result.get("provider") or settings.ai_image_provider
    analysis.after_photo_status = status
    analysis.after_photo_variant_paths = variant_paths
    analysis.after_photo_final_path = final_path
    analysis.after_photo_quality_results = quality_results
    analysis.after_photo_used_intensity = result.get("used_intensity")
    analysis.after_photo_retry_count = int(result.get("retry_count") or 0)
    analysis.after_photo_path = final_path if status == AFTER_PHOTO_APPROVED else None
    analysis.after_photo_variants = [
        {
            "index": index,
            "path": path,
            "status": "generated",
        }
        for index, path in enumerate(variant_paths, start=1)
    ]
    analysis.after_photo_plan = {
        "legacy": False,
        "pipeline": AFTER_PHOTO_PIPELINE,
        "prompt_source": AFTER_PHOTO_PROMPT_SOURCE,
        "provider": provider,
        "image_model": (
            settings.ai_image_model_openai or settings.openai_after_photo_image_model or settings.openai_protocol_image_model or "gpt-image-2"
            if provider == "openai"
            else settings.ai_image_model_gemini or settings.gemini_protocol_image_model or settings.gemini_model
        ),
        "intensity": result.get("used_intensity"),
        "negative_prompt": prompt_payload.get("negative_prompt"),
        "structured_focus": prompt_payload.get("structured_focus") or result.get("structured_focus"),
        "variant_count": settings.after_photo_variant_count,
        "retry_count": result.get("retry_count") or 0,
        "reason": result.get("reason") or "",
        "fallback_used": result.get("fallback_used") or False,
        "crop": result.get("crop"),
        "quality_used_vision_qa": result.get("quality_used_vision_qa"),
    }

    image = (
        db.query(GeneratedImage)
        .filter(GeneratedImage.analysis_id == analysis.id, GeneratedImage.kind == "after_photo")
        .order_by(GeneratedImage.id.desc())
        .first()
    )
    if not image:
        image = GeneratedImage(analysis_id=analysis.id, kind="after_photo")
        db.add(image)
    image.status = "completed" if status == AFTER_PHOTO_APPROVED else status.lower()
    image.path = final_path
    image.prompt = prompt_payload.get("prompt")
    image.negative_prompt = prompt_payload.get("negative_prompt")
    image.metadata_json = {
        "pipeline": AFTER_PHOTO_PIPELINE,
        "status": status,
        "variant_paths": variant_paths,
        "quality_results": quality_results,
        "used_intensity": result.get("used_intensity"),
        "used_retry": result.get("used_retry"),
        "retry_count": result.get("retry_count"),
        "reason": result.get("reason"),
        "provider": provider,
        "fallback_used": result.get("fallback_used") or False,
        "crop": result.get("crop"),
        "structured_focus": prompt_payload.get("structured_focus") or result.get("structured_focus"),
        "quality_used_vision_qa": result.get("quality_used_vision_qa"),
    }


def _generate_after_photo(analysis_id: int, preferred_intensity: str | None = None) -> None:
    db = SessionLocal()
    try:
        analysis = db.query(AnalysisRequest).filter(AnalysisRequest.id == analysis_id).first()
        if not analysis or not analysis.original_photo_path:
            raise ValueError("Анализ не найден или нет исходного фото")
        if not after_photo_feature_enabled():
            _mark_after_photo_disabled(db, analysis)
            return

        intensity = "visible"
        analysis_json = _wait_for_analysis_json(db, analysis)
        selected_problems = analysis.selected_problems or []
        prompt_payload = build_after_photo_prompt(
            intensity,
            attempt_index=3,
            analysis_json=analysis_json,
            selected_problems=selected_problems,
        )
        logger.info("AFTER_PHOTO_PIPELINE=%s", AFTER_PHOTO_PIPELINE)
        logger.info("Selected intensity: %s", intensity)

        analysis.after_photo_status = AFTER_PHOTO_PROCESSING
        analysis.after_photo_used_intensity = intensity
        analysis.after_photo_retry_count = 0
        provider = choose_image_provider_for_user(analysis.telegram_user.telegram_id if analysis.telegram_user else analysis.id)
        analysis.after_photo_plan = {
            "legacy": False,
            "pipeline": AFTER_PHOTO_PIPELINE,
            "prompt_source": AFTER_PHOTO_PROMPT_SOURCE,
            "provider": provider,
            "image_model": (
                settings.ai_image_model_openai or settings.openai_after_photo_image_model or settings.openai_protocol_image_model or "gpt-image-2"
                if provider == "openai"
                else settings.ai_image_model_gemini or settings.gemini_protocol_image_model or settings.gemini_model
            ),
            "intensity": intensity,
            "variant_count": settings.after_photo_variant_count,
            "negative_prompt": prompt_payload.get("negative_prompt"),
            "structured_focus": prompt_payload.get("structured_focus"),
            "experiment_mode": settings.ai_experiment_mode,
        }
        db.commit()

        try:
            from app.workers.tasks_telegram import enqueue_analysis_progress_update

            enqueue_analysis_progress_update(analysis.id, "after_photo")
        except Exception:
            logger.warning("Could not enqueue after-photo progress update", exc_info=True)

        input_abs = local_storage.abs_path(analysis.original_photo_path)
        started = time.perf_counter()
        provider_result = generate_after_photo_with_fallback(
            analysis_request_id=str(analysis.id),
            photo_path=input_abs,
            user_key=analysis.telegram_user.telegram_id if analysis.telegram_user else analysis.id,
            intensity=intensity,
            analysis_json=analysis_json,
            selected_problems=selected_problems,
        )
        result = provider_result.payload
        result["provider"] = provider_result.provider
        result["fallback_used"] = provider_result.fallback_used
        image_time_ms = provider_result.latency_ms or int((time.perf_counter() - started) * 1000)
        _persist_result(db, analysis, result, prompt_payload)
        db.commit()

        log_job(
            db,
            analysis.id,
            "after_photo",
            "success" if result.get("status") == AFTER_PHOTO_APPROVED else "manual_review",
            result.get("final_path") or result.get("status") or "",
            result,
        )
        log_job(
            db,
            analysis.id,
            "ai_image_performance",
            "success" if result.get("status") in {AFTER_PHOTO_APPROVED, AFTER_PHOTO_NEEDS_MANUAL_REVIEW} else "failed",
            result.get("reason") or result.get("status") or "",
            {
                "jobId": analysis.id,
                "userId": analysis.telegram_user.telegram_id if analysis.telegram_user else None,
                "imageProvider": provider_result.provider,
                "imageTimeMs": image_time_ms,
                "fallbackUsed": provider_result.fallback_used,
                "success": result.get("status") in {AFTER_PHOTO_APPROVED, AFTER_PHOTO_NEEDS_MANUAL_REVIEW},
                "status": result.get("status"),
                "errorMessage": result.get("reason") or provider_result.error,
                "experimentMode": settings.ai_experiment_mode,
                "crop": result.get("crop"),
                "structuredFocus": result.get("structured_focus") or prompt_payload.get("structured_focus"),
            },
        )

        logger.info(
            "After-photo finished for analysis %s with status %s; Telegram delivery is handled by the embedded protocol flow",
            analysis.id,
            result.get("status"),
        )
    except Exception as exc:
        logger.exception("After-photo generation failed")
        analysis = db.query(AnalysisRequest).filter(AnalysisRequest.id == analysis_id).first()
        if analysis:
            analysis.after_photo_status = AFTER_PHOTO_FAILED
            analysis.after_photo_plan = {
                "legacy": False,
                "pipeline": AFTER_PHOTO_PIPELINE,
                "error": str(exc),
                "provider": settings.ai_image_provider,
            }
            image = GeneratedImage(analysis_id=analysis_id, kind="after_photo", status="failed", metadata_json={"error": str(exc)})
            db.add(image)
            db.commit()
        log_job(db, analysis_id, "after_photo", "failed", str(exc))
    finally:
        db.close()


@celery_app.task(
    name="app.workers.tasks_after_photo.generate_after_photo_task",
    bind=True,
    autoretry_for=(),
    retry_kwargs={"max_retries": settings.after_photo_retry_count},
    retry_backoff=True,
)
def generate_after_photo_task(self, analysis_id: int, preferred_intensity: str | None = None) -> None:
    _generate_after_photo(analysis_id, preferred_intensity)


def enqueue_after_photo(analysis_id: int, preferred_intensity: str | None = None, run_sync_fallback: bool = False) -> None:
    if not after_photo_feature_enabled():
        db = SessionLocal()
        try:
            analysis = db.query(AnalysisRequest).filter(AnalysisRequest.id == analysis_id).first()
            if analysis:
                _mark_after_photo_disabled(db, analysis)
        finally:
            db.close()
        return
    try:
        generate_after_photo_task.apply_async(args=[analysis_id, preferred_intensity], queue="after_photo")
    except Exception:
        if run_sync_fallback:
            _generate_after_photo(analysis_id, preferred_intensity)
        else:
            logger.warning("Celery broker unavailable; after-photo parallel task was not started")
