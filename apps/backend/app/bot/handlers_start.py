from __future__ import annotations

from datetime import datetime, timezone

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot.funnel import welcome_text
from app.bot.keyboards import consent_keyboard
from app.bot.states import FaceProtocolStates
from app.db.crm import add_lead_event, apply_source_link_to_lead, touch_lead
from app.db.models import AnalysisStatus, CampaignSource, EventLog, Lead, TelegramUser
from app.db.repositories import get_bot_settings
from app.db.session import SessionLocal

router = Router()


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    payload = (message.text or "").split(maxsplit=1)[1] if message.text and len(message.text.split(maxsplit=1)) > 1 else None
    db = SessionLocal()
    try:
        source_link = None
        if payload:
            source_link = (
                db.query(CampaignSource)
                .filter(CampaignSource.start_payload == payload, CampaignSource.is_active.is_(True))
                .first()
            )
            if source_link:
                source_link.clicks += 1
        user = db.query(TelegramUser).filter(TelegramUser.telegram_id == message.from_user.id).first()
        if not user:
            user = TelegramUser(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name,
                language_code=message.from_user.language_code,
                current_status=AnalysisStatus.WAITING_FOR_CONSENT,
                start_payload=payload,
                campaign=source_link,
                last_bot_interaction_at=datetime.now(timezone.utc),
            )
            db.add(user)
            db.flush()
        else:
            user.username = message.from_user.username
            user.first_name = message.from_user.first_name
            user.last_name = message.from_user.last_name
            user.current_status = AnalysisStatus.WAITING_FOR_CONSENT
            user.unsubscribed = False
            user.unsubscribed_at = None
            user.last_bot_interaction_at = datetime.now(timezone.utc)
            user.start_payload = payload or user.start_payload
            if source_link:
                user.campaign = source_link
        lead = user.lead
        if not lead:
            lead = Lead(
                telegram_user_id=user.id,
                status=AnalysisStatus.WAITING_FOR_CONSENT,
                source=(source_link.source if source_link else payload),
            )
            db.add(lead)
            db.flush()
        else:
            lead.status = AnalysisStatus.WAITING_FOR_CONSENT
            lead.source = (source_link.source if source_link else payload) or lead.source
        touch_lead(lead)
        if source_link:
            apply_source_link_to_lead(db, lead, source_link, payload)
        add_lead_event(db, lead, "start", "Пользователь нажал /start", {"source": payload})
        db.add(EventLog(telegram_user_id=user.id, lead_id=lead.id if lead.id else None, event_type="start", payload={"source": payload}))
        db.commit()
        bot_settings = get_bot_settings(db)
        await state.clear()
        await state.set_state(FaceProtocolStates.waiting_for_consent)
        await message.answer(welcome_text())
        await message.answer(bot_settings.consent_text, reply_markup=consent_keyboard())
    finally:
        db.close()
