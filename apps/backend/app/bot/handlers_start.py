from __future__ import annotations

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot.funnel import name_request_text, welcome_text
from app.bot.states import FaceProtocolStates
from app.db.crm import add_lead_event, apply_source_link_to_lead, touch_lead
from app.db.models import AnalysisStatus, CampaignSource, EventLog, Lead, TelegramUser
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
                current_status=AnalysisStatus.WAITING_FOR_NAME,
                start_payload=payload,
                campaign=source_link,
            )
            db.add(user)
            db.flush()
        else:
            user.username = message.from_user.username
            user.first_name = message.from_user.first_name
            user.last_name = message.from_user.last_name
            user.current_status = AnalysisStatus.WAITING_FOR_NAME
            user.start_payload = payload or user.start_payload
            if source_link:
                user.campaign = source_link
        lead = user.lead
        if not lead:
            lead = Lead(
                telegram_user_id=user.id,
                status=AnalysisStatus.WAITING_FOR_NAME,
                source=(source_link.source if source_link else payload),
            )
            db.add(lead)
            db.flush()
        else:
            lead.status = AnalysisStatus.WAITING_FOR_NAME
            lead.source = (source_link.source if source_link else payload) or lead.source
        touch_lead(lead)
        if source_link:
            apply_source_link_to_lead(db, lead, source_link, payload)
        add_lead_event(db, lead, "start", "Пользователь нажал /start", {"source": payload})
        db.add(EventLog(telegram_user_id=user.id, lead_id=lead.id if lead.id else None, event_type="start", payload={"source": payload}))
        db.commit()
        await state.clear()
        await state.set_state(FaceProtocolStates.waiting_for_name)
        await message.answer(welcome_text())
        await message.answer(name_request_text())
    finally:
        db.close()
