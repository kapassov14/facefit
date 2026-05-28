from __future__ import annotations

from pathlib import Path

from app.ai.prompts import (
    AFTER_PHOTO_NEGATIVE_PROMPT,
    AFTER_PHOTO_PROMPT,
    DEFAULT_ANALYSIS_SYSTEM_PROMPT,
    DISCLAIMER,
    PROTOCOL_PROMPT,
    PROTOCOL_SLIDE_COPY_SYSTEM_PROMPT,
    PROTOCOL_SLIDE_COPY_USER_PROMPT,
    REPORT_PROMPT,
    load_default_system_prompt,
)
from app.core.config import settings
from app.core.security import hash_password
from app.db.models import AdminRole, AdminUser, BotSettings, CampaignSource, KnowledgeChunk, KnowledgeDocument, PromptTemplate
from app.db.session import SessionLocal, engine
from app.db.models import Base
from app.knowledge.chunker import chunk_text


PROBLEM_CATALOG = [
    {"slug": "nasolabial", "title": "Носогубные складки"},
    {"slug": "glabella", "title": "Межбровная морщина"},
    {"slug": "eyes", "title": "Нависшее веко / мешки под глазами"},
    {"slug": "oval", "title": "Потеря овала / брыли"},
    {"slug": "double_chin", "title": "Второй подбородок"},
    {"slug": "puffiness", "title": "Отечность и усталый вид"},
    {"slug": "skin_tone", "title": "Тонус и цвет кожи"},
]


def _read_default_knowledge() -> str:
    local = Path(__file__).parents[1] / "knowledge" / "default_knowledge_base.md"
    if local.exists():
        return local.read_text(encoding="utf-8")
    downloaded = Path("/Users/alo/Downloads/knowledge_base.md")
    if downloaded.exists():
        return downloaded.read_text(encoding="utf-8")
    return "Методика Bella Vladi: лимфодренаж, мышечный тонус, расслабление зажимов, осанка и дыхание."


def seed() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        admin = db.query(AdminUser).filter(AdminUser.email == settings.admin_email).first()
        if not admin:
            db.add(
                AdminUser(
                    email=settings.admin_email,
                    password_hash=hash_password(settings.admin_password),
                    role=AdminRole.OWNER,
                    is_active=True,
                )
            )

        prompt_definitions = [
            ("analysis_system", "System prompt анализа", load_default_system_prompt() or DEFAULT_ANALYSIS_SYSTEM_PROMPT),
            ("short_protocol", "Prompt краткого протокола", PROTOCOL_PROMPT),
            (
                "protocol_slide_copy",
                "Prompt slide-safe JSON для Telegram протокола",
                f"{PROTOCOL_SLIDE_COPY_SYSTEM_PROMPT}\n\n{PROTOCOL_SLIDE_COPY_USER_PROMPT}",
            ),
            ("detailed_report", "Prompt подробного отчета", REPORT_PROMPT),
            ("after_photo", "Prompt after-photo", AFTER_PHOTO_PROMPT),
            ("after_photo_negative", "Negative prompt after-photo", AFTER_PHOTO_NEGATIVE_PROMPT),
            ("bot_tone", "Тон коммуникации бота", "Теплый, экспертный, бережный, без давления и медицинских диагнозов."),
            ("disclaimer", "Disclaimer", DISCLAIMER),
        ]
        for key, name, content in prompt_definitions:
            if not db.query(PromptTemplate).filter(PromptTemplate.key == key).first():
                db.add(
                    PromptTemplate(
                        key=key,
                        name=name,
                        content=content,
                        variables=[
                            "user_name",
                            "selected_problems",
                            "knowledge_context",
                            "analysis_json",
                            "photo_url",
                            "report_url",
                            "date",
                        ],
                    )
                )

        if not db.query(BotSettings).first():
            db.add(
                BotSettings(
                    welcome_text=(
                        "Привет! Это Белла 🤍\n\n"
                        "Этот бот проанализирует твоё лицо по моей авторской методике и даст точные персональные рекомендации."
                    ),
                    consent_text=(
                        "Перед началом подтвердите, пожалуйста, что вы добровольно отправляете фото для визуального анализа. "
                        "Анализ не является медицинским диагнозом, не заменяет консультацию врача или косметолога и используется "
                        "только для формирования персонального face-протокола."
                    ),
                    photo_instruction_text=(
                        "Для персонального протокола мне нужно твоё фото анфас при дневном освещении, без фильтров."
                    ),
                    waiting_text="Подготавливаю твой персональный протокол... ⏳\nЭто займёт около минуты.",
                    after_analysis_text="Готово! Вот твой персональный протокол лица.",
                    disclaimer=DISCLAIMER,
                    cta_text="Получить персональную программу",
                    instagram_url="",
                    whatsapp_url="",
                    telegram_url="",
                    after_photo_enabled=True,
                    manual_moderation_enabled=False,
                    regeneration_enabled=True,
                    analysis_limit_per_user=100,
                    problem_catalog=PROBLEM_CATALOG,
                    ai_settings={
                        "temperature": 0.35,
                        "max_tokens": 2500,
                        "retry_count": settings.ai_retry_count,
                        "timeout": settings.ai_timeout_seconds,
                        "queue_concurrency": settings.queue_concurrency,
                        "enable_gemini_fallback": settings.enable_gemini_fallback,
                        "enable_after_photo": settings.enable_after_photo,
                        "after_photo_pipeline": "universal_prompt_v1",
                        "after_photo_provider": settings.after_photo_provider,
                        "after_photo_image_model": settings.openai_after_photo_image_model if settings.after_photo_provider == "openai" else settings.replicate_flux_model,
                        "after_photo_default_intensity": settings.after_photo_default_intensity,
                        "after_photo_variant_count": settings.after_photo_variant_count,
                        "after_photo_retry_count": settings.after_photo_retry_count,
                    },
                )
            )

        if not db.query(CampaignSource).filter(CampaignSource.slug == "test_campaign").first():
            bot_name = settings.telegram_bot_username or "YOUR_BOT_USERNAME"
            db.add(
                CampaignSource(
                    slug="test_campaign",
                    title="Тестовая кампания",
                    start_payload="test_campaign",
                    url=f"https://t.me/{bot_name}?start=test_campaign",
                )
            )

        if not db.query(KnowledgeDocument).filter(KnowledgeDocument.filename == "default_knowledge_base.md").first():
            content = _read_default_knowledge()
            document = KnowledgeDocument(
                title="База знаний Bella Vladi",
                filename="default_knowledge_base.md",
                mime_type="text/markdown",
                content=content,
                is_active=True,
            )
            db.add(document)
            db.flush()
            for index, chunk in enumerate(chunk_text(content), start=1):
                db.add(KnowledgeChunk(document_id=document.id, chunk_index=index, content=chunk, is_active=True))

        db.commit()
        print("Seed completed: admin, prompts, settings, knowledge base and test campaign are ready.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
