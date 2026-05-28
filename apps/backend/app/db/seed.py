from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
from app.core.config import settings, validate_production_settings
from app.core.security import hash_password
from app.db.models import (
    AdminNote,
    AdminRole,
    AdminUser,
    AudienceBase,
    AudienceBaseMember,
    Base,
    BotSettings,
    Broadcast,
    CampaignSource,
    ClientStatus,
    KnowledgeChunk,
    KnowledgeDocument,
    Lead,
    LeadActivity,
    LeadEvent,
    LeadTag,
    LeadTask,
    PromptTemplate,
    Tag,
    TelegramUser,
)
from app.db.session import SessionLocal, engine
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
    validate_production_settings()
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        admin = db.query(AdminUser).filter(AdminUser.email == settings.admin_email).first()
        if not admin:
            admin = AdminUser(
                name="Owner",
                email=settings.admin_email,
                password_hash=hash_password(settings.admin_password),
                role=AdminRole.OWNER,
                is_active=True,
                can_broadcast=True,
            )
            db.add(admin)
        else:
            admin.name = admin.name or "Owner"
            admin.role = AdminRole.OWNER
            admin.can_broadcast = True
        db.flush()

        demo_managers = [
            ("manager1@bella.local", "Анна менеджер"),
            ("manager2@bella.local", "Мария менеджер"),
        ]
        managers: list[AdminUser] = []
        for email, name in demo_managers:
            manager = db.query(AdminUser).filter(AdminUser.email == email).first()
            if not manager:
                manager = AdminUser(
                    name=name,
                    email=email,
                    password_hash=hash_password("manager12345"),
                    role=AdminRole.MANAGER,
                    is_active=True,
                    can_broadcast=True,
                )
                db.add(manager)
                db.flush()
            managers.append(manager)

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
                    after_photo_enabled=False,
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
                        "enable_after_photo": False,
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

        demo_tag_defs = [
            ("горячий", "#f4c7c4"),
            ("теплый", "#f4d99e"),
            ("оплатил", "#cfe7d4"),
            ("нужен звонок", "#d9d2f2"),
            ("VIP", "#f0d8ea"),
            ("нецелевой", "#d7d2cc"),
        ]
        tag_by_name: dict[str, Tag] = {}
        for name, color in demo_tag_defs:
            tag = db.query(Tag).filter(Tag.name == name).first()
            if not tag:
                tag = Tag(name=name, color=color)
                db.add(tag)
                db.flush()
            tag_by_name[name] = tag

        base_defs = [
            ("Теплая база", "static", {}, "Лиды с открытым отчетом и интересом"),
            (
                "Получили протокол",
                "dynamic",
                {"status": [ClientStatus.PROTOCOL_SENT, ClientStatus.REPORT_OPENED, ClientStatus.CTA_CLICKED]},
                "Авто-сегмент по статусам",
            ),
            ("Нажали CTA", "dynamic", {"cta_clicked": True}, "Горячий динамический сегмент"),
        ]
        bases: list[AudienceBase] = []
        for name, base_type, filters, description in base_defs:
            base = db.query(AudienceBase).filter(AudienceBase.name == name).first()
            if not base:
                base = AudienceBase(name=name, type=base_type, filters_json=filters, description=description, created_by_id=admin.id)
                db.add(base)
                db.flush()
            bases.append(base)

        if db.query(Lead).filter(Lead.source == "demo_seed").count() < 20:
            statuses = [
                ClientStatus.NEW,
                ClientStatus.PHOTO_SENT,
                ClientStatus.PROTOCOL_SENT,
                ClientStatus.REPORT_OPENED,
                ClientStatus.CTA_CLICKED,
                ClientStatus.MANUAL_CONTACT,
                ClientStatus.IN_DIALOG,
                ClientStatus.THINKING,
                ClientStatus.PAID,
                ClientStatus.NOT_RELEVANT,
                ClientStatus.ARCHIVED,
            ]
            problems = [
                ["Овал лица", "Брыли"],
                ["Зона глаз", "Отечность"],
                ["Носогубные складки"],
                ["Межбровная морщина", "Тонус кожи"],
                ["Второй подбородок", "Овал лица"],
            ]
            now = datetime.now(timezone.utc)
            for index in range(20):
                telegram_id = 900000000 + index
                user = db.query(TelegramUser).filter(TelegramUser.telegram_id == telegram_id).first()
                if not user:
                    user = TelegramUser(
                        telegram_id=telegram_id,
                        username=f"demo_user_{index + 1}",
                        first_name=f"Demo {index + 1}",
                        language_code="ru",
                        is_blocked=index in {17, 18},
                        blocked_at=now - timedelta(days=1) if index in {17, 18} else None,
                        unsubscribed=index == 19,
                        unsubscribed_at=now - timedelta(days=2) if index == 19 else None,
                        last_bot_interaction_at=now - timedelta(days=index % 9),
                    )
                    db.add(user)
                    db.flush()
                if user.lead:
                    continue
                status_value = statuses[index % len(statuses)]
                manager = managers[index % len(managers)]
                lead = Lead(
                    telegram_user_id=user.id,
                    name=f"Клиент {index + 1}",
                    age=25 + (index % 18),
                    status="COMPLETED" if status_value in {ClientStatus.PROTOCOL_SENT, ClientStatus.REPORT_OPENED, ClientStatus.CTA_CLICKED, ClientStatus.PAID} else "WAITING_FOR_PHOTO",
                    selected_problems=problems[index % len(problems)],
                    report_opened=status_value in {ClientStatus.REPORT_OPENED, ClientStatus.CTA_CLICKED, ClientStatus.PAID},
                    cta_clicked=status_value in {ClientStatus.CTA_CLICKED, ClientStatus.PAID},
                    source="demo_seed",
                    utm={"campaign": "Demo May"},
                    crm_status=status_value,
                    assigned_manager_id=manager.id if index % 3 else None,
                    assigned_at=now - timedelta(days=index) if index % 3 else None,
                    assigned_by_id=admin.id if index % 3 else None,
                    last_activity_at=now - timedelta(hours=index * 5),
                    manager_comment="Демо-лид для проверки CRM" if index % 4 == 0 else None,
                )
                db.add(lead)
                db.flush()
                selected_tag_names = ["теплый"] if status_value in {ClientStatus.REPORT_OPENED, ClientStatus.THINKING} else []
                if status_value in {ClientStatus.CTA_CLICKED, ClientStatus.MANUAL_CONTACT}:
                    selected_tag_names.append("горячий")
                if status_value == ClientStatus.PAID:
                    selected_tag_names.append("оплатил")
                if index % 7 == 0:
                    selected_tag_names.append("нужен звонок")
                lead.tags = selected_tag_names
                for tag_name in selected_tag_names:
                    db.add(LeadTag(lead_id=lead.id, tag_id=tag_by_name[tag_name].id))
                db.add(LeadEvent(lead_id=lead.id, type="user_started_bot", title="Демо: пользователь запустил бота", metadata_json={}, created_by_id=None))
                db.add(LeadActivity(lead_id=lead.id, actor_type="system", event_type="user_started_bot", payload_json={"demo": True}))
                db.add(LeadActivity(lead_id=lead.id, actor_type="system", event_type="status_changed", payload_json={"to": status_value}))
                if index % 5 == 0:
                    db.add(AdminNote(lead_id=lead.id, admin_id=manager.id, text="Демо-заметка: уточнить интерес и предложить консультацию."))
                if bases and index % 2 == 0:
                    db.add(AudienceBaseMember(base_id=bases[0].id, lead_id=lead.id, telegram_user_id=user.id, added_by_id=admin.id))
                if index % 4 == 0:
                    db.add(
                        LeadTask(
                            lead_id=lead.id,
                            assigned_to_id=manager.id,
                            title="Связаться с лидом",
                            description="Демо-задача для проверки списка задач и бейджа на карточке.",
                            due_at=now + timedelta(days=(index % 3) - 1),
                            status="todo",
                            created_by_id=admin.id,
                        )
                    )

        if not db.query(Broadcast).filter(Broadcast.title == "Demo: приветствие теплой базы").first() and bases:
            db.add(
                Broadcast(
                    title="Demo: приветствие теплой базы",
                    base_id=bases[0].id,
                    status="draft",
                    message_type="text",
                    message_text="Привет! Подготовили для вас персональные рекомендации по face fitness.",
                    text="Привет! Подготовили для вас персональные рекомендации по face fitness.",
                    buttons_json=[{"text": "Открыть консультацию", "url": "https://example.com"}],
                    buttons=[{"text": "Открыть консультацию", "url": "https://example.com"}],
                    created_by_id=admin.id,
                    rate_limit_per_second=10,
                )
            )
        if not db.query(Broadcast).filter(Broadcast.title == "Demo: CTA follow-up").first() and len(bases) > 2:
            db.add(
                Broadcast(
                    title="Demo: CTA follow-up",
                    base_id=bases[2].id,
                    status="scheduled",
                    message_type="text",
                    message_text="Вижу, что вам интересна программа. Хотите, менеджер подберет удобный формат?",
                    text="Вижу, что вам интересна программа. Хотите, менеджер подберет удобный формат?",
                    created_by_id=admin.id,
                    scheduled_at=datetime.now(timezone.utc) + timedelta(days=1),
                    rate_limit_per_second=5,
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
        print("Seed completed: admins, demo CRM, bases, broadcasts, prompts, settings, knowledge base and test campaign are ready.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
