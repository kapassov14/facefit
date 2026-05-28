from datetime import datetime, timezone

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot.funnel import age_request_text, photo_instruction_text
from app.bot.states import FaceProtocolStates
from app.db.crm import add_lead_event
from app.db.models import AnalysisStatus, TelegramUser
from app.db.session import SessionLocal

router = Router()


@router.message(FaceProtocolStates.waiting_for_name)
async def receive_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()[:120]
    if len(name) < 2:
        await message.answer("Напишите, пожалуйста, имя текстом, чтобы я красиво подписала протокол.")
        return
    db = SessionLocal()
    try:
        user = db.query(TelegramUser).filter(TelegramUser.telegram_id == message.from_user.id).first()
        if user and user.lead:
            user.last_bot_interaction_at = datetime.now(timezone.utc)
            user.lead.name = name
            user.lead.status = AnalysisStatus.WAITING_FOR_AGE
            user.current_status = AnalysisStatus.WAITING_FOR_AGE
            add_lead_event(db, user.lead, "answered_name", "Пользователь оставил имя", {"name": name})
            db.commit()
        await state.set_state(FaceProtocolStates.waiting_for_age)
        await message.answer(age_request_text(name))
    finally:
        db.close()


@router.message(FaceProtocolStates.waiting_for_age)
async def receive_age(message: Message, state: FSMContext) -> None:
    raw = " ".join((message.text or "").split()).strip().lower()
    age: int | None = None
    if raw not in {"пропустить", "skip", "не хочу", "нет"}:
        digits = "".join(ch for ch in raw if ch.isdigit())
        if not digits:
            await message.answer("Напишите возраст цифрой, например 34. Или отправьте «пропустить».")
            return
        age = int(digits[:3])
        if age < 16 or age > 90:
            await message.answer("Кажется, возраст указан некорректно. Напишите цифрой от 16 до 90 или «пропустить».")
            return
    db = SessionLocal()
    try:
        user = db.query(TelegramUser).filter(TelegramUser.telegram_id == message.from_user.id).first()
        name = user.lead.name if user and user.lead else None
        if user and user.lead:
            user.last_bot_interaction_at = datetime.now(timezone.utc)
            user.lead.age = age
            user.lead.status = AnalysisStatus.WAITING_FOR_PHOTO
            user.current_status = AnalysisStatus.WAITING_FOR_PHOTO
            add_lead_event(db, user.lead, "answered_age", "Пользователь указал возраст", {"age": age})
            db.commit()
        await state.set_state(FaceProtocolStates.waiting_for_photo)
        await message.answer(photo_instruction_text(name))
    finally:
        db.close()
