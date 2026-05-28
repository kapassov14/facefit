from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from aiogram import Bot
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile

from app.bot import funnel
from app.bot.progress import get_progress_message, progress_text, should_apply_stage
from app.core.config import settings
from app.db.crm import add_lead_event
from app.db.models import AiJobLog, AnalysisRequest, ClientStatus, EventLog, GeneratedImage, LeadEvent
from app.db.session import SessionLocal
from app.storage.local import local_storage
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _log_job(analysis_id: int | None, stage: str, status: str, message: str | None = None, payload: dict | None = None) -> None:
    db = SessionLocal()
    try:
        db.add(AiJobLog(analysis_id=analysis_id, stage=stage, status=status, message=message, payload=payload or {}))
        db.commit()
    finally:
        db.close()


def _has_successful_telegram_send(db, analysis_id: int) -> bool:
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


async def _send_ready_message(
    telegram_id: int,
    protocol_image_path: str,
    report_url: str,
    protocol_version: str,
    zone_protocol_image_path: str | None = None,
) -> None:
    if not settings.telegram_bot_token:
        return
    if protocol_version != "final_v1":
        raise RuntimeError("Expected final_v1 face protocol for new analysis")
    if not protocol_image_path or not Path(protocol_image_path).exists():
        raise RuntimeError("Expected final_v1 PNG at face_protocol_image_path")

    bot = Bot(settings.telegram_bot_token)
    try:
        await bot.send_chat_action(telegram_id, ChatAction.UPLOAD_PHOTO)
        await bot.send_photo(
            telegram_id,
            FSInputFile(protocol_image_path),
            caption=funnel.protocol_ready_caption(),
        )
        if (
            zone_protocol_image_path
            and Path(zone_protocol_image_path).exists()
            and Path(zone_protocol_image_path).resolve() != Path(protocol_image_path).resolve()
        ):
            await bot.send_chat_action(telegram_id, ChatAction.UPLOAD_PHOTO)
            await bot.send_photo(
                telegram_id,
                FSInputFile(zone_protocol_image_path),
                caption=funnel.zone_protocol_caption(),
            )
    finally:
        await bot.session.close()


async def edit_progress_message(bot: Bot, chat_id: int, message_id: int, text: str) -> bool:
    try:
        await bot.send_chat_action(chat_id, ChatAction.TYPING)
        await bot.edit_message_text(text=text, chat_id=chat_id, message_id=message_id)
        return True
    except TelegramBadRequest as exc:
        if "message is not modified" in str(exc).lower():
            return True
        logger.warning("Could not edit Telegram progress message: %s", exc)
        return False


async def _send_after_photo(telegram_id: int, image_path: str) -> None:
    if not settings.telegram_bot_token:
        return
    bot = Bot(settings.telegram_bot_token)
    try:
        await bot.send_photo(
            telegram_id,
            FSInputFile(image_path),
            caption=(
                "Возможная визуализация результата при регулярной работе 3 месяца. "
                "Это не гарантия результата, а мягкий ориентир."
            ),
        )
    finally:
        await bot.session.close()


async def _send_after_photo_pending_message(telegram_id: int) -> None:
    if not settings.telegram_bot_token:
        return
    bot = Bot(settings.telegram_bot_token)
    try:
        await bot.send_message(
            telegram_id,
            "Визуализация результата еще формируется. Если потребуется, мы доработаем ее отдельно.",
        )
    finally:
        await bot.session.close()


async def _send_after_photo_retry_message(telegram_id: int) -> None:
    if not settings.telegram_bot_token:
        return
    bot = Bot(settings.telegram_bot_token)
    try:
        await bot.send_message(
            telegram_id,
            "After-photo не получилось сгенерировать достаточно заметно и реалистично. "
            "Я не отправляю исходное фото вместо результата — визуализацию нужно перезапустить или доработать отдельно.",
        )
    finally:
        await bot.session.close()


def _event_exists(db, analysis_id: int, event_type: str) -> bool:
    analysis = db.query(AnalysisRequest).filter(AnalysisRequest.id == analysis_id).first()
    if not analysis or not analysis.lead_id:
        return False
    return (
        db.query(LeadEvent)
        .filter(LeadEvent.lead_id == analysis.lead_id, LeadEvent.type == event_type)
        .first()
        is not None
    )


def _record_funnel_event(db, analysis: AnalysisRequest, event_type: str, title: str, payload: dict | None = None) -> None:
    if analysis.lead:
        add_lead_event(db, analysis.lead, event_type, title, {"analysis_id": analysis.id, **(payload or {})})
    if analysis.telegram_user:
        db.add(
            EventLog(
                telegram_user_id=analysis.telegram_user.id,
                lead_id=analysis.lead_id,
                event_type=event_type,
                payload={"analysis_id": analysis.id, **(payload or {})},
            )
        )


def _should_skip_sales_message(analysis: AnalysisRequest | None) -> bool:
    if not analysis or not analysis.telegram_user:
        return True
    if analysis.lead and analysis.lead.crm_status == ClientStatus.BOUGHT:
        return True
    return False


async def _send_after_visual_offer_message(analysis: AnalysisRequest) -> None:
    if not settings.telegram_bot_token or not analysis.telegram_user:
        return
    bot = Bot(settings.telegram_bot_token)
    try:
        text = funnel.after_visual_text(analysis.lead.name if analysis.lead else None)
        image_path = analysis.after_photo_final_path or analysis.after_photo_path
        if image_path:
            abs_path = local_storage.abs_path(image_path)
            if Path(abs_path).exists():
                await bot.send_chat_action(analysis.telegram_user.telegram_id, ChatAction.UPLOAD_PHOTO)
                await bot.send_photo(
                    analysis.telegram_user.telegram_id,
                    FSInputFile(abs_path),
                    caption=text,
                    reply_markup=funnel.after_visual_keyboard(analysis.id),
                )
                return
        await bot.send_message(
            analysis.telegram_user.telegram_id,
            text,
            reply_markup=funnel.after_visual_keyboard(analysis.id),
        )
    finally:
        await bot.session.close()


async def _send_training_message(analysis: AnalysisRequest) -> None:
    if not settings.telegram_bot_token or not analysis.telegram_user:
        return
    bot = Bot(settings.telegram_bot_token)
    try:
        video_path = funnel.training_video_path()
        if video_path:
            await bot.send_chat_action(analysis.telegram_user.telegram_id, ChatAction.UPLOAD_VIDEO)
            await bot.send_video(
                analysis.telegram_user.telegram_id,
                FSInputFile(video_path),
                caption=funnel.training_text(),
            )
            return
        await bot.send_message(analysis.telegram_user.telegram_id, funnel.training_text())
    finally:
        await bot.session.close()


async def _send_offer_message(analysis: AnalysisRequest) -> None:
    if not settings.telegram_bot_token or not analysis.telegram_user:
        return
    bot = Bot(settings.telegram_bot_token)
    try:
        for media_path in funnel.case_media_paths():
            await bot.send_chat_action(analysis.telegram_user.telegram_id, ChatAction.UPLOAD_PHOTO)
            await bot.send_photo(analysis.telegram_user.telegram_id, FSInputFile(media_path))
        await bot.send_message(
            analysis.telegram_user.telegram_id,
            funnel.offer_text(analysis.lead.name if analysis.lead else None, analysis.selected_problems or []),
            reply_markup=funnel.offer_keyboard(analysis.id),
        )
    finally:
        await bot.session.close()


async def _send_bonus_reminder_message(analysis: AnalysisRequest) -> None:
    if not settings.telegram_bot_token or not analysis.telegram_user:
        return
    bot = Bot(settings.telegram_bot_token)
    try:
        await bot.send_message(
            analysis.telegram_user.telegram_id,
            funnel.bonus_reminder_text(analysis.lead.name if analysis.lead else None),
            reply_markup=funnel.bonus_keyboard(analysis.id),
        )
    finally:
        await bot.session.close()


@celery_app.task(name="app.workers.tasks_telegram.send_analysis_ready_message_task", bind=True)
def send_analysis_ready_message_task(self, analysis_id: int, report_url: str, force: bool = False) -> None:
    db = SessionLocal()
    started = time.perf_counter()
    try:
        analysis = db.query(AnalysisRequest).filter(AnalysisRequest.id == analysis_id).with_for_update().first()
        if not analysis or not analysis.telegram_user:
            return
        if not force and _has_successful_telegram_send(db, analysis.id):
            db.add(
                AiJobLog(
                    analysis_id=analysis.id,
                    stage="telegram_send",
                    status="skipped",
                    message="Protocol already sent; duplicate Telegram task ignored",
                    payload={"userId": analysis.telegram_user.telegram_id, "jobId": analysis.id},
                )
            )
            db.commit()
            return
        if analysis.face_protocol_version != "final_v1":
            raise RuntimeError("Expected final_v1 face protocol for new analysis")
        if not analysis.face_protocol_image_path:
            raise RuntimeError("Expected final_v1 PNG path was empty")
        zone_protocol_abs = None
        zone_image = (
            db.query(GeneratedImage)
            .filter(
                GeneratedImage.analysis_id == analysis.id,
                GeneratedImage.kind == "face_zone_protocol",
                GeneratedImage.status == "completed",
            )
            .order_by(GeneratedImage.created_at.desc())
            .first()
        )
        if zone_image and zone_image.path:
            zone_protocol_abs = local_storage.abs_path(zone_image.path)
        protocol_png_abs = zone_protocol_abs or local_storage.abs_path(analysis.face_protocol_image_path)
        asyncio.run(
            _send_ready_message(
                analysis.telegram_user.telegram_id,
                protocol_png_abs,
                report_url,
                analysis.face_protocol_version,
                zone_protocol_abs,
            )
        )
        asyncio.run(_replace_progress_with_result(analysis.id, analysis.telegram_user.telegram_id, report_url))
        _record_funnel_event(db, analysis, "protocol_sent", "Пользователю отправлен персональный протокол")
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        db.add(
            AiJobLog(
                analysis_id=analysis.id,
                stage="telegram_send",
                status="success",
                message="Final protocol and report link sent",
                payload={"telegramSendTimeMs": elapsed_ms, "userId": analysis.telegram_user.telegram_id, "jobId": analysis.id},
            )
        )
        db.commit()
        enqueue_after_visual_offer(analysis.id)
    except Exception as exc:
        logger.exception("Telegram final protocol send failed")
        _log_job(analysis_id, "telegram_send", "failed", str(exc))
        raise
    finally:
        db.close()


async def _replace_progress_with_result(analysis_id: int, telegram_id: int, report_url: str) -> None:
    if not settings.telegram_bot_token:
        return
    if not should_apply_stage(analysis_id, "ready"):
        return
    progress = get_progress_message(analysis_id)
    bot = Bot(settings.telegram_bot_token)
    try:
        if progress:
            await edit_progress_message(
                bot,
                progress.chat_id,
                progress.message_id,
                progress_text("ready"),
            )
        await bot.send_message(
            telegram_id,
            f"Подробный web-отчет:\n{report_url}",
        )
    finally:
        await bot.session.close()


@celery_app.task(name="app.workers.tasks_telegram.update_analysis_progress_task", bind=True)
def update_analysis_progress_task(self, analysis_id: int, stage: str) -> None:
    if not settings.telegram_bot_token:
        return
    if not should_apply_stage(analysis_id, stage):
        return
    progress = get_progress_message(analysis_id)
    if not progress:
        return
    try:
        asyncio.run(_edit_analysis_progress(progress.chat_id, progress.message_id, progress_text(stage)))
        _log_job(analysis_id, "telegram_progress", "success", stage)
    except Exception as exc:
        logger.warning("Telegram progress update failed: %s", exc)
        _log_job(analysis_id, "telegram_progress", "failed", str(exc), {"stage": stage})


async def _edit_analysis_progress(chat_id: int, message_id: int, text: str) -> None:
    bot = Bot(settings.telegram_bot_token)
    try:
        await edit_progress_message(bot, chat_id, message_id, text)
    finally:
        await bot.session.close()


@celery_app.task(name="app.workers.tasks_telegram.send_after_photo_message_task", bind=True)
def send_after_photo_message_task(self, analysis_id: int) -> None:
    db = SessionLocal()
    started = time.perf_counter()
    try:
        analysis = db.query(AnalysisRequest).filter(AnalysisRequest.id == analysis_id).first()
        if not analysis or not analysis.telegram_user or not analysis.after_photo_final_path:
            return
        final_abs = local_storage.abs_path(analysis.after_photo_final_path)
        if not Path(final_abs).exists():
            raise RuntimeError("Approved after-photo file was not found")
        asyncio.run(_send_after_photo(analysis.telegram_user.telegram_id, final_abs))
        _log_job(
            analysis.id,
            "telegram_after_photo",
            "success",
            "After-photo sent",
            {"telegramSendTimeMs": int((time.perf_counter() - started) * 1000), "userId": analysis.telegram_user.telegram_id, "jobId": analysis.id},
        )
    except Exception as exc:
        logger.exception("Telegram after-photo send failed")
        _log_job(analysis_id, "telegram_after_photo", "failed", str(exc))
        raise
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks_telegram.send_after_photo_pending_message_task", bind=True)
def send_after_photo_pending_message_task(self, analysis_id: int) -> None:
    _send_after_photo_status_message(analysis_id, "pending")


@celery_app.task(name="app.workers.tasks_telegram.send_after_photo_retry_message_task", bind=True)
def send_after_photo_retry_message_task(self, analysis_id: int) -> None:
    _send_after_photo_status_message(analysis_id, "retry")


def _send_after_photo_status_message(analysis_id: int, kind: str) -> None:
    db = SessionLocal()
    try:
        analysis = db.query(AnalysisRequest).filter(AnalysisRequest.id == analysis_id).first()
        if not analysis or not analysis.telegram_user:
            return
        if kind == "retry":
            asyncio.run(_send_after_photo_retry_message(analysis.telegram_user.telegram_id))
        else:
            asyncio.run(_send_after_photo_pending_message(analysis.telegram_user.telegram_id))
        _log_job(analysis.id, f"telegram_after_photo_{kind}", "success", datetime.now(timezone.utc).isoformat())
    except Exception as exc:
        logger.exception("Telegram after-photo status message failed")
        _log_job(analysis_id, f"telegram_after_photo_{kind}", "failed", str(exc))
        raise
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks_telegram.send_after_visual_offer_task", bind=True)
def send_after_visual_offer_task(self, analysis_id: int) -> None:
    db = SessionLocal()
    started = time.perf_counter()
    try:
        analysis = db.query(AnalysisRequest).filter(AnalysisRequest.id == analysis_id).first()
        if _should_skip_sales_message(analysis):
            return
        event_type = "funnel_after_visual_offer_sent"
        if _event_exists(db, analysis_id, event_type):
            return
        asyncio.run(_send_after_visual_offer_message(analysis))
        _record_funnel_event(db, analysis, event_type, "Отправлен дожим с after-фото и приглашением на тренировку")
        db.commit()
        _log_job(
            analysis_id,
            "funnel_after_visual_offer",
            "success",
            "After visual offer sent",
            {"telegramSendTimeMs": int((time.perf_counter() - started) * 1000), "jobId": analysis_id},
        )
    except Exception as exc:
        logger.exception("Telegram after visual offer failed")
        _log_job(analysis_id, "funnel_after_visual_offer", "failed", str(exc))
        raise
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks_telegram.send_training_message_task", bind=True)
def send_training_message_task(self, analysis_id: int) -> None:
    db = SessionLocal()
    try:
        analysis = db.query(AnalysisRequest).filter(AnalysisRequest.id == analysis_id).first()
        if _should_skip_sales_message(analysis):
            return
        if _event_exists(db, analysis_id, "funnel_training_sent"):
            return
        asyncio.run(_send_training_message(analysis))
        _record_funnel_event(db, analysis, "funnel_training_sent", "Пользователю отправлена бесплатная тренировка")
        db.commit()
        enqueue_offer_after_training(analysis_id)
        _log_job(analysis_id, "funnel_training", "success", "Training message sent")
    except Exception as exc:
        logger.exception("Telegram training message failed")
        _log_job(analysis_id, "funnel_training", "failed", str(exc))
        raise
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks_telegram.send_offer_message_task", bind=True)
def send_offer_message_task(self, analysis_id: int) -> None:
    db = SessionLocal()
    started = time.perf_counter()
    try:
        analysis = db.query(AnalysisRequest).filter(AnalysisRequest.id == analysis_id).first()
        if _should_skip_sales_message(analysis):
            return
        event_type = "funnel_offer_sent"
        if _event_exists(db, analysis_id, event_type):
            return
        asyncio.run(_send_offer_message(analysis))
        _record_funnel_event(db, analysis, event_type, "Отправлен оффер курса с бонусами и рассрочкой")
        db.commit()
        enqueue_bonus_reminder(analysis_id)
        _log_job(
            analysis_id,
            "funnel_offer",
            "success",
            "Offer message sent",
            {"telegramSendTimeMs": int((time.perf_counter() - started) * 1000), "jobId": analysis_id},
        )
    except Exception as exc:
        logger.exception("Telegram offer message failed")
        _log_job(analysis_id, "funnel_offer", "failed", str(exc))
        raise
    finally:
        db.close()


@celery_app.task(name="app.workers.tasks_telegram.send_bonus_reminder_task", bind=True)
def send_bonus_reminder_task(self, analysis_id: int) -> None:
    db = SessionLocal()
    try:
        analysis = db.query(AnalysisRequest).filter(AnalysisRequest.id == analysis_id).first()
        if _should_skip_sales_message(analysis):
            return
        event_type = "funnel_bonus_reminder_sent"
        if _event_exists(db, analysis_id, event_type):
            return
        asyncio.run(_send_bonus_reminder_message(analysis))
        _record_funnel_event(db, analysis, event_type, "Отправлен дожим с бонусами")
        db.commit()
        _log_job(analysis_id, "funnel_bonus_reminder", "success", "Bonus reminder sent")
    except Exception as exc:
        logger.exception("Telegram bonus reminder failed")
        _log_job(analysis_id, "funnel_bonus_reminder", "failed", str(exc))
        raise
    finally:
        db.close()


def enqueue_analysis_ready_message(analysis_id: int, report_url: str, force: bool = False) -> None:
    send_analysis_ready_message_task.apply_async(args=[analysis_id, report_url, force], queue="telegram")


def enqueue_analysis_progress_update(analysis_id: int, stage: str) -> None:
    update_analysis_progress_task.apply_async(args=[analysis_id, stage], queue="telegram")


def enqueue_after_photo_message(analysis_id: int) -> None:
    send_after_photo_message_task.apply_async(args=[analysis_id], queue="telegram")


def enqueue_after_photo_pending_message(analysis_id: int) -> None:
    send_after_photo_pending_message_task.apply_async(args=[analysis_id], queue="telegram")


def enqueue_after_photo_retry_message(analysis_id: int) -> None:
    send_after_photo_retry_message_task.apply_async(args=[analysis_id], queue="telegram")


def enqueue_after_visual_offer(analysis_id: int) -> None:
    send_after_visual_offer_task.apply_async(args=[analysis_id], queue="telegram", countdown=funnel.AFTER_VISUAL_DELAY_SECONDS)


def enqueue_training_message(analysis_id: int) -> None:
    send_training_message_task.apply_async(args=[analysis_id], queue="telegram")


def enqueue_offer_after_training(analysis_id: int) -> None:
    send_offer_message_task.apply_async(args=[analysis_id], queue="telegram", countdown=funnel.OFFER_DELAY_SECONDS)


def enqueue_bonus_reminder(analysis_id: int) -> None:
    send_bonus_reminder_task.apply_async(args=[analysis_id], queue="telegram", countdown=funnel.BONUS_DELAY_SECONDS)
