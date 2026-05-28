from sqlalchemy.orm import Session

from app.db.models import BotSettings, PromptTemplate


def get_bot_settings(db: Session) -> BotSettings:
    settings = db.query(BotSettings).order_by(BotSettings.id.asc()).first()
    if settings:
        return settings
    settings = BotSettings(
        welcome_text=(
            "Привет! Это Белла 🤍\n\n"
            "Этот бот проанализирует твоё лицо по моей авторской методике и даст точные персональные рекомендации."
        ),
        consent_text="Перед началом подтвердите, пожалуйста, что вы добровольно отправляете фото для визуального анализа.",
        photo_instruction_text="Для персонального протокола мне нужно твоё фото анфас при дневном освещении, без фильтров.",
        waiting_text="Подготавливаю твой персональный протокол... ⏳\nЭто займёт около минуты.",
        after_analysis_text="Готово! Вот твой персональный протокол лица.",
        disclaimer="Анализ не является медицинским диагнозом и используется только для персонального face-протокола.",
        problem_catalog=[],
    )
    db.add(settings)
    db.commit()
    db.refresh(settings)
    return settings


def get_prompt(db: Session, key: str, default: str = "") -> str:
    prompt = db.query(PromptTemplate).filter(PromptTemplate.key == key, PromptTemplate.is_active.is_(True)).first()
    return prompt.content if prompt else default
