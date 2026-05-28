from __future__ import annotations

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from app.bot.keyboards import problems_keyboard, title_by_slug
from app.bot.progress import progress_text, save_progress_message
from app.bot.states import FaceProtocolStates
from app.db.crm import add_lead_event
from app.db.models import AnalysisRequest, AnalysisStatus, SelectedProblem
from app.db.repositories import get_bot_settings
from app.db.session import SessionLocal
from app.workers.tasks_analysis import enqueue_analysis

router = Router()


@router.callback_query(FaceProtocolStates.waiting_for_problems, lambda callback: callback.data and callback.data.startswith("problem:"))
async def choose_problem(callback: CallbackQuery, state: FSMContext) -> None:
    slug = callback.data.split(":", 1)[1]
    db = SessionLocal()
    try:
        settings = get_bot_settings(db)
        data = await state.get_data()
        selected: set[str] = set(data.get("selected_problems", []))
        analysis_id = data.get("analysis_id")
        analysis = db.query(AnalysisRequest).filter(AnalysisRequest.id == analysis_id).first()
        if not analysis:
            await callback.message.answer("Не нашла заявку. Пожалуйста, начните заново через /start.")
            await callback.answer()
            return
        if slug == "done":
            titles = [title_by_slug(item, settings.problem_catalog or []) for item in selected]
            if not titles:
                await callback.answer("Выберите хотя бы одну зону", show_alert=True)
                return
            analysis.selected_problems = titles
            analysis.status = AnalysisStatus.QUEUED
            if analysis.lead:
                analysis.lead.selected_problems = titles
                analysis.lead.status = AnalysisStatus.QUEUED
                add_lead_event(db, analysis.lead, "problems_selected", "Пользователь выбрал зоны внимания", {"problems": titles})
            if analysis.telegram_user:
                analysis.telegram_user.current_status = AnalysisStatus.QUEUED
            db.query(SelectedProblem).filter(SelectedProblem.analysis_id == analysis.id).delete()
            for item in selected:
                db.add(SelectedProblem(analysis_id=analysis.id, slug=item, title=title_by_slug(item, settings.problem_catalog or [])))
            db.commit()
            await state.clear()
            progress_message = await callback.message.answer(progress_text("queued"))
            save_progress_message(
                analysis.id,
                progress_message.chat.id,
                progress_message.message_id,
                "queued",
            )
            enqueue_analysis(analysis.id)
            await callback.answer()
            return
        if slug in selected:
            selected.remove(slug)
        else:
            selected.add(slug)
        await state.update_data(selected_problems=list(selected))
        await callback.message.edit_reply_markup(reply_markup=problems_keyboard(settings.problem_catalog or [], selected))
        await callback.answer()
    finally:
        db.close()
