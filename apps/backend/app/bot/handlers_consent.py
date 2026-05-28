from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from app.bot.states import FaceProtocolStates
from app.db.crm import add_lead_event
from app.db.models import AnalysisStatus, TelegramUser
from app.db.session import SessionLocal

router = Router()


@router.callback_query(lambda callback: callback.data in {"consent:yes", "consent:no"})
async def consent(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.data == "consent:no":
        await callback.message.answer("Понимаю. Если захотите вернуться к face-протоколу, просто нажмите /start.")
        await callback.answer()
        return
    db = SessionLocal()
    try:
        user = db.query(TelegramUser).filter(TelegramUser.telegram_id == callback.from_user.id).first()
        if user:
            user.current_status = AnalysisStatus.WAITING_FOR_NAME
            if user.lead:
                user.lead.status = AnalysisStatus.WAITING_FOR_NAME
                add_lead_event(db, user.lead, "consent_accepted", "Пользователь подтвердил согласие")
            db.commit()
        await state.set_state(FaceProtocolStates.waiting_for_name)
        await callback.message.answer("Как к Вам обращаться? Напишите, пожалуйста, имя.")
        await callback.answer()
    finally:
        db.close()
