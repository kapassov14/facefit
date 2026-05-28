from __future__ import annotations

import io
import secrets
from datetime import datetime, timezone
from pathlib import Path

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from PIL import Image

from app.bot.funnel import problems_prompt_text
from app.bot.keyboards import problems_keyboard
from app.bot.states import FaceProtocolStates
from app.db.crm import add_lead_event
from app.db.models import AnalysisRequest, AnalysisStatus, CampaignSource, ClientStatus, TelegramUser
from app.db.repositories import get_bot_settings
from app.db.session import SessionLocal
from app.reports.face_zone_protocol.mediapipe_map import validate_face_photo
from app.storage.local import local_storage

router = Router()


def _is_valid_photo(data: bytes) -> bool:
    try:
        image = Image.open(io.BytesIO(data))
        width, height = image.size
        return width >= 500 and height >= 500
    except Exception:
        return False


@router.message(FaceProtocolStates.waiting_for_photo)
async def receive_photo(message: Message, state: FSMContext) -> None:
    if not message.photo:
        await message.answer("Пожалуйста, отправьте именно фото лица. Лучше анфас, при дневном свете и без сильных фильтров.")
        return
    buffer = io.BytesIO()
    await message.bot.download(message.photo[-1], destination=buffer)
    data = buffer.getvalue()
    if not _is_valid_photo(data):
        await message.answer("Фото получилось слишком маленьким или не читается. Пришлите, пожалуйста, другое фото лица анфас.")
        return

    db = SessionLocal()
    try:
        settings = get_bot_settings(db)
        user = db.query(TelegramUser).filter(TelegramUser.telegram_id == message.from_user.id).first()
        if not user or not user.lead:
            await message.answer("Давайте начнем заново: нажмите /start.")
            return
        user.last_bot_interaction_at = datetime.now(timezone.utc)
        analyses_count = db.query(AnalysisRequest).filter(AnalysisRequest.telegram_user_id == user.id).count()
        if analyses_count >= settings.analysis_limit_per_user:
            await message.answer("Лимит анализов для одного пользователя уже использован. Напишите эксперту, если нужен повторный протокол.")
            return
        relative_path = f"photos/{secrets.token_urlsafe(24)}.jpg"
        local_storage.save_bytes(relative_path, data)
        photo_quality = validate_face_photo(local_storage.abs_path(relative_path))
        if not photo_quality.get("ok"):
            Path(local_storage.abs_path(relative_path)).unlink(missing_ok=True)
            await message.answer(
                photo_quality.get("message")
                or "Фото не подходит для точного анализа. Пришлите фото лица анфас при хорошем свете, без сильного наклона и без закрывающих лицо волос или рук."
            )
            return
        analysis = AnalysisRequest(
            telegram_user_id=user.id,
            lead_id=user.lead.id,
            status=AnalysisStatus.WAITING_FOR_PROBLEMS,
            original_photo_path=relative_path,
        )
        db.add(analysis)
        user.current_status = AnalysisStatus.WAITING_FOR_PROBLEMS
        user.lead.status = AnalysisStatus.WAITING_FOR_PROBLEMS
        user.lead.crm_status = ClientStatus.PHOTO_SENT
        add_lead_event(db, user.lead, "photo_uploaded", "Пользователь отправил фото", {"path": relative_path})
        if user.campaign:
            campaign: CampaignSource = user.campaign
            campaign.photo_count += 1
        db.commit()
        await state.set_state(FaceProtocolStates.waiting_for_problems)
        await state.update_data(analysis_id=analysis.id, selected_problems=[])
        await message.answer(
            problems_prompt_text(user.lead.name),
            reply_markup=problems_keyboard(settings.problem_catalog or [], set()),
        )
    finally:
        db.close()
