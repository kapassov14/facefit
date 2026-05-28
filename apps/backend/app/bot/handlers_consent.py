from datetime import datetime, timezone

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from app.bot.states import FaceProtocolStates
from app.db.crm import add_lead_event
from app.db.models import AnalysisStatus, EventLog, TelegramUser
from app.db.session import SessionLocal

router = Router()


@router.callback_query(lambda callback: callback.data in {"consent:yes", "consent:no"})
async def consent(callback: CallbackQuery, state: FSMContext) -> None:
    db = SessionLocal()
    try:
        user = db.query(TelegramUser).filter(TelegramUser.telegram_id == callback.from_user.id).first()
        if not user:
            await state.clear()
            await callback.message.answer("Давайте начнем заново: нажмите /start.")
            await callback.answer()
            return
        user.last_bot_interaction_at = datetime.now(timezone.utc)
        if callback.data == "consent:no":
            user.current_status = AnalysisStatus.WAITING_FOR_CONSENT
            if user.lead:
                user.lead.status = AnalysisStatus.WAITING_FOR_CONSENT
                add_lead_event(db, user.lead, "consent_declined", "Пользователь отказался от согласия")
            db.add(EventLog(telegram_user_id=user.id, lead_id=user.lead.id if user.lead else None, event_type="consent_declined", payload={}))
            db.commit()
            await state.clear()
            await callback.message.answer("Понимаю. Если захотите вернуться к face-протоколу, просто нажмите /start.")
            await callback.answer()
            return
        if user:
            user.current_status = AnalysisStatus.WAITING_FOR_NAME
            if user.lead:
                user.lead.status = AnalysisStatus.WAITING_FOR_NAME
                add_lead_event(db, user.lead, "consent_accepted", "Пользователь подтвердил согласие")
            db.add(EventLog(telegram_user_id=user.id, lead_id=user.lead.id if user.lead else None, event_type="consent_accepted", payload={}))
            db.commit()
        await state.set_state(FaceProtocolStates.waiting_for_name)
        await callback.message.answer("Как к Вам обращаться? Напишите, пожалуйста, имя.")
        await callback.answer()
    finally:
        db.close()
