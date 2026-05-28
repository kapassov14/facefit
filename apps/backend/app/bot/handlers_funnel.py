from __future__ import annotations

from aiogram import Router
from aiogram.types import CallbackQuery

from app.bot import funnel
from app.db.crm import add_lead_event, touch_lead
from app.db.models import AnalysisRequest, ClientStatus, TelegramUser
from app.db.session import SessionLocal
from app.workers.tasks_telegram import enqueue_training_message

router = Router()


def _parse_callback(data: str | None) -> tuple[str, int | None]:
    parts = (data or "").split(":")
    if len(parts) < 2 or parts[0] != "funnel":
        return "", None
    analysis_id = None
    if len(parts) >= 3:
        try:
            analysis_id = int(parts[2])
        except ValueError:
            analysis_id = None
    return parts[1], analysis_id


def _latest_analysis(db, telegram_id: int, analysis_id: int | None) -> AnalysisRequest | None:
    query = (
        db.query(AnalysisRequest)
        .join(TelegramUser, AnalysisRequest.telegram_user_id == TelegramUser.id)
        .filter(TelegramUser.telegram_id == telegram_id)
    )
    if analysis_id:
        found = query.filter(AnalysisRequest.id == analysis_id).first()
        if found:
            return found
    return query.order_by(AnalysisRequest.id.desc()).first()


def _record_click(db, analysis: AnalysisRequest | None, event_type: str, title: str) -> None:
    if not analysis:
        return
    if analysis.lead:
        touch_lead(analysis.lead)
        if event_type in {"training_requested", "course_more_clicked", "bonuses_clicked"} and analysis.lead.crm_status == ClientStatus.NEW:
            analysis.lead.crm_status = ClientStatus.WARMING
        if event_type == "questions_clicked":
            analysis.lead.crm_status = ClientStatus.WAITING_REPLY
        if event_type in {"course_buy_clicked", "installment_clicked"} and analysis.lead.crm_status != ClientStatus.BOUGHT:
            analysis.lead.crm_status = ClientStatus.APPLIED
        add_lead_event(db, analysis.lead, event_type, title, {"analysis_id": analysis.id})
    if analysis.telegram_user and analysis.telegram_user.campaign and event_type in {"course_buy_clicked", "installment_clicked"}:
        analysis.telegram_user.campaign.cta_clicks += 1
    if analysis.lead and event_type in {"course_buy_clicked", "installment_clicked"}:
        analysis.lead.cta_clicked = True


@router.callback_query(lambda callback: callback.data and callback.data.startswith("funnel:"))
async def funnel_callback(callback: CallbackQuery) -> None:
    action, analysis_id = _parse_callback(callback.data)
    db = SessionLocal()
    try:
        analysis = _latest_analysis(db, callback.from_user.id, analysis_id)
        if not analysis:
            await callback.message.answer("Не нашла твой протокол. Нажми /start, и мы начнем заново.")
            await callback.answer()
            return

        if action == "training":
            _record_click(db, analysis, "training_requested", "Пользователь запросил бесплатную тренировку")
            db.commit()
            enqueue_training_message(analysis.id)
            await callback.answer("Отправляю тренировку 🤍")
            return

        if action == "course_more":
            _record_click(db, analysis, "course_more_clicked", "Пользователь запросил подробности о курсе")
            db.commit()
            await callback.message.answer(funnel.course_more_text(), reply_markup=funnel.offer_keyboard(analysis.id))
            await callback.answer()
            return

        if action == "questions":
            _record_click(db, analysis, "questions_clicked", "Пользователь нажал Есть вопросы")
            db.commit()
            await callback.message.answer(
                funnel.questions_text(),
                reply_markup=funnel.link_keyboard("Написать менеджеру", funnel.fallback_manager_url()),
            )
            await callback.answer()
            return

        if action == "buy":
            _record_click(db, analysis, "course_buy_clicked", "Пользователь нажал купить курс")
            db.commit()
            await callback.message.answer(
                "Отлично 🔥 Забрать курс можно по ссылке ниже.",
                reply_markup=funnel.link_keyboard("Перейти к оплате", funnel.fallback_course_url()),
            )
            await callback.answer()
            return

        if action == "installment":
            _record_click(db, analysis, "installment_clicked", "Пользователь нажал рассрочку")
            db.commit()
            await callback.message.answer(
                "Да, можно начать через рассрочку: 1 200 руб. в месяц без переплат.",
                reply_markup=funnel.link_keyboard("Открыть рассрочку", funnel.fallback_installment_url()),
            )
            await callback.answer()
            return

        if action == "bonuses":
            _record_click(db, analysis, "bonuses_clicked", "Пользователь запросил список бонусов")
            db.commit()
            await callback.message.answer(funnel.bonus_details_text(), reply_markup=funnel.bonus_keyboard(analysis.id))
            await callback.answer()
            return

        await callback.answer()
    finally:
        db.close()
