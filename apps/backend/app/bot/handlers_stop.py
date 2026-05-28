from __future__ import annotations

from datetime import datetime, timezone

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.db.crm import add_lead_event
from app.db.models import EventLog, TelegramUser
from app.db.session import SessionLocal

router = Router()


@router.message(Command("stop"))
async def stop(message: Message, state: FSMContext) -> None:
    db = SessionLocal()
    try:
        user = db.query(TelegramUser).filter(TelegramUser.telegram_id == message.from_user.id).first()
        if user:
            now = datetime.now(timezone.utc)
            user.unsubscribed = True
            user.unsubscribed_at = now
            user.last_bot_interaction_at = now
            if user.lead:
                add_lead_event(db, user.lead, "unsubscribed", "Пользователь отправил /stop")
            db.add(EventLog(telegram_user_id=user.id, lead_id=user.lead.id if user.lead else None, event_type="unsubscribed", payload={"source": "stop_command"}))
            db.commit()
        await state.clear()
        await message.answer("Вы отписались от сообщений бота. Чтобы вернуться, нажмите /start.")
    finally:
        db.close()
