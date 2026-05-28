from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import String, cast, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import AnalysisRequest, AudienceBase, AudienceBaseMember, Broadcast, BroadcastRecipient, Lead, TelegramUser
from app.db.session import SessionLocal
from app.storage.local import local_storage
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _dynamic_lead_query(db: Session, filters: dict[str, Any]):
    query = db.query(Lead)
    if filters.get("status"):
        values = filters["status"] if isinstance(filters["status"], list) else [filters["status"]]
        query = query.filter(Lead.crm_status.in_(values))
    if filters.get("problem"):
        problem = str(filters["problem"])
        query = query.filter(
            Lead.selected_problems.contains([problem])
            if db.bind and db.bind.dialect.name == "postgresql"
            else cast(Lead.selected_problems, String).ilike(f"%{problem}%")
        )
    if filters.get("report_opened") is not None:
        query = query.filter(Lead.report_opened.is_(bool(filters["report_opened"])))
    if filters.get("cta_clicked") is not None:
        query = query.filter(Lead.cta_clicked.is_(bool(filters["cta_clicked"])))
    if filters.get("tag"):
        tag = str(filters["tag"])
        query = query.filter(Lead.tags.contains([tag]) if db.bind and db.bind.dialect.name == "postgresql" else cast(Lead.tags, String).ilike(f"%{tag}%"))
    if filters.get("source"):
        query = query.filter(Lead.source == filters["source"])
    if filters.get("manager_id"):
        query = query.filter(Lead.assigned_manager_id == int(filters["manager_id"]))
    if filters.get("after_photo_status"):
        query = query.filter(Lead.analyses.any(AnalysisRequest.after_photo_status == str(filters["after_photo_status"])))
    return query


def _legacy_audience_query(db: Session, audience_filter: dict):
    query = db.query(Lead)
    segment = audience_filter.get("segment")
    if segment == "no_photo":
        query = query.filter(Lead.status.in_(["WAITING_FOR_PHOTO", "WAITING_FOR_PROBLEMS"]))
    elif segment == "got_report":
        query = query.filter(Lead.status.in_(["COMPLETED", "NEEDS_REVIEW"]))
    elif segment == "report_opened":
        query = query.filter(Lead.report_opened.is_(True))
    elif segment == "no_cta":
        query = query.filter(Lead.cta_clicked.is_(False))
    return _dynamic_lead_query(db, audience_filter) if segment in {None, "all"} else query


def _recipient_users(db: Session, broadcast: Broadcast) -> list[TelegramUser]:
    if broadcast.base_id:
        base = db.query(AudienceBase).filter(AudienceBase.id == broadcast.base_id).first()
        if not base:
            return []
        if base.type == "dynamic":
            lead_query = _dynamic_lead_query(db, base.filters_json or {})
        else:
            lead_query = db.query(Lead).join(AudienceBaseMember, AudienceBaseMember.lead_id == Lead.id).filter(AudienceBaseMember.base_id == base.id)
    else:
        lead_query = _legacy_audience_query(db, broadcast.audience_filter or {})
    return (
        db.query(TelegramUser)
        .join(Lead, Lead.telegram_user_id == TelegramUser.id)
        .filter(
            Lead.id.in_(lead_query.with_entities(Lead.id)),
            TelegramUser.is_blocked.is_(False),
            TelegramUser.unsubscribed.is_(False),
        )
        .order_by(TelegramUser.id.asc())
        .all()
    )


def _keyboard(buttons: list[dict[str, str]]) -> InlineKeyboardMarkup | None:
    if not buttons:
        return None
    rows = [
        [InlineKeyboardButton(text=button.get("text", "Открыть"), url=button.get("url"))]
        for button in buttons
        if button.get("url")
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def _message_text(broadcast: Broadcast) -> str:
    return broadcast.message_text or broadcast.text or ""


def _buttons(broadcast: Broadcast) -> list[dict[str, str]]:
    return broadcast.buttons_json or broadcast.buttons or []


async def _send_to_user(bot: Bot, telegram_id: int, broadcast: Broadcast):
    markup = _keyboard(_buttons(broadcast))
    text = _message_text(broadcast)
    media_kind = broadcast.media_type or broadcast.message_type
    media_source = broadcast.media_url or broadcast.media_path
    if media_source:
        payload = media_source if media_source.startswith("http") else FSInputFile(local_storage.abs_path(media_source))
        if media_kind == "photo":
            return await bot.send_photo(telegram_id, payload, caption=text or None, reply_markup=markup)
        if media_kind == "video":
            return await bot.send_video(telegram_id, payload, caption=text or None, reply_markup=markup)
        if media_kind == "document":
            return await bot.send_document(telegram_id, payload, caption=text or None, reply_markup=markup)
    return await bot.send_message(telegram_id, text, reply_markup=markup)


def _is_blocked_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(
        marker in text
        for marker in [
            "bot was blocked",
            "bot was kicked",
            "chat not found",
            "user is deactivated",
            "forbidden",
        ]
    )


def _mark_user_message_result(user: TelegramUser, error: Exception | None = None) -> None:
    now = datetime.now(timezone.utc)
    if error:
        user.last_message_error = str(error)[:2000]
        if _is_blocked_error(error):
            user.is_blocked = True
            user.blocked_at = now
    else:
        user.last_message_sent_at = now
        user.last_message_error = None


def _ensure_recipient(db: Session, broadcast: Broadcast, user: TelegramUser) -> BroadcastRecipient:
    recipient = (
        db.query(BroadcastRecipient)
        .filter(BroadcastRecipient.broadcast_id == broadcast.id, BroadcastRecipient.telegram_user_id == user.id)
        .first()
    )
    if recipient:
        return recipient
    recipient = BroadcastRecipient(broadcast_id=broadcast.id, telegram_user_id=user.id, status="pending")
    db.add(recipient)
    db.flush()
    return recipient


async def _send_broadcast_async(broadcast_id: int) -> None:
    db = SessionLocal()
    bot = Bot(settings.telegram_bot_token) if settings.telegram_bot_token else None
    try:
        broadcast = db.query(Broadcast).filter(Broadcast.id == broadcast_id).first()
        if not broadcast:
            return
        users = _recipient_users(db, broadcast)
        broadcast.status = "sending"
        broadcast.started_at = datetime.now(timezone.utc)
        db.commit()
        delay = 1 / max(int(broadcast.rate_limit_per_second or 10), 1)
        sent = 0
        failed = 0
        skipped = 0
        for user in users:
            db.refresh(broadcast)
            if broadcast.status in {"paused", "cancelled"}:
                break
            recipient = _ensure_recipient(db, broadcast, user)
            if recipient.status in {"sent", "mock_sent", "blocked", "skipped_unsubscribed"}:
                skipped += 1
                continue
            if user.unsubscribed or user.is_blocked:
                recipient.status = "skipped_unsubscribed" if user.unsubscribed else "blocked"
                db.commit()
                skipped += 1
                continue
            try:
                if bot:
                    message = await _send_to_user(bot, user.telegram_id, broadcast)
                    recipient.status = "sent"
                    recipient.telegram_message_id = getattr(message, "message_id", None)
                else:
                    recipient.status = "mock_sent"
                now = datetime.now(timezone.utc)
                recipient.sent_at = now
                recipient.delivered_at = now
                _mark_user_message_result(user)
                sent += 1
            except TelegramRetryAfter as exc:
                await asyncio.sleep(float(exc.retry_after))
                recipient.status = "pending"
                recipient.error_message = str(exc)
            except (TelegramForbiddenError, TelegramBadRequest, Exception) as exc:
                _mark_user_message_result(user, exc)
                recipient.status = "blocked" if _is_blocked_error(exc) else "failed"
                recipient.error_message = str(exc)[:2000]
                failed += 1
            db.commit()
            await asyncio.sleep(delay)
        db.refresh(broadcast)
        if broadcast.status not in {"paused", "cancelled"}:
            broadcast.status = "completed" if failed == 0 else ("completed" if sent else "failed")
            broadcast.completed_at = datetime.now(timezone.utc)
            broadcast.sent_at = broadcast.completed_at
        db.commit()
        logger.info("broadcast %s finished: sent=%s failed=%s skipped=%s", broadcast_id, sent, failed, skipped)
    finally:
        if bot:
            await bot.session.close()
        db.close()


async def send_test_broadcast_async(broadcast_id: int, telegram_id: int) -> dict:
    db = SessionLocal()
    bot = Bot(settings.telegram_bot_token) if settings.telegram_bot_token else None
    try:
        broadcast = db.query(Broadcast).filter(Broadcast.id == broadcast_id).first()
        if not broadcast:
            return {"ok": False, "error": "broadcast_not_found"}
        if bot:
            message = await _send_to_user(bot, telegram_id, broadcast)
            return {"ok": True, "status": "sent", "telegram_message_id": getattr(message, "message_id", None)}
        return {"ok": True, "status": "mock_sent"}
    finally:
        if bot:
            await bot.session.close()
        db.close()


@celery_app.task(name="app.workers.tasks_broadcast.send_broadcast_task", bind=True)
def send_broadcast_task(self, broadcast_id: int) -> None:
    asyncio.run(_send_broadcast_async(broadcast_id))


@celery_app.task(name="app.workers.tasks_broadcast.send_due_broadcasts_task", bind=True)
def send_due_broadcasts_task(self) -> int:
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        broadcasts = (
            db.query(Broadcast)
            .filter(Broadcast.status == "scheduled", Broadcast.scheduled_at.is_not(None), Broadcast.scheduled_at <= now)
            .order_by(Broadcast.scheduled_at.asc())
            .limit(50)
            .all()
        )
        count = 0
        for broadcast in broadcasts:
            broadcast.status = "queued"
            count += 1
            send_broadcast_task.apply_async(args=[broadcast.id], queue="telegram")
        db.commit()
        return count
    finally:
        db.close()


def enqueue_broadcast(broadcast_id: int) -> None:
    send_broadcast_task.apply_async(args=[broadcast_id], queue="telegram")
