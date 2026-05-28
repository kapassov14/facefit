from __future__ import annotations

import secrets
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )


class AnalysisStatus:
    WAITING_FOR_CONSENT = "WAITING_FOR_CONSENT"
    WAITING_FOR_NAME = "WAITING_FOR_NAME"
    WAITING_FOR_AGE = "WAITING_FOR_AGE"
    WAITING_FOR_PHOTO = "WAITING_FOR_PHOTO"
    WAITING_FOR_PROBLEMS = "WAITING_FOR_PROBLEMS"
    QUEUED = "QUEUED"
    ANALYZING = "ANALYZING"
    GENERATING_PROTOCOL = "GENERATING_PROTOCOL"
    GENERATING_REPORT = "GENERATING_REPORT"
    GENERATING_AFTER_PHOTO = "GENERATING_AFTER_PHOTO"
    COMPLETED = "COMPLETED"
    FAILED_PROTOCOL_RENDER = "FAILED_PROTOCOL_RENDER"
    FAILED = "FAILED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class AdminRole:
    OWNER = "owner"
    MANAGER = "manager"
    VIEWER = "viewer"


class ClientStatus:
    NEW = "new"
    WARMING = "warming"
    APPLIED = "applied"
    WAITING_REPLY = "waiting_reply"
    IN_PROGRESS = "in_progress"
    BOUGHT = "bought"
    REJECTED = "rejected"
    NO_ANSWER = "no_answer"
    ARCHIVED = "archived"


class AdminUser(Base, TimestampMixin):
    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default=AdminRole.MANAGER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Audience(Base, TimestampMixin):
    __tablename__ = "audiences"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    color: Mapped[str] = mapped_column(String(32), default="#be7d86")

    leads: Mapped[list["Lead"]] = relationship(back_populates="audience")
    source_links: Mapped[list["CampaignSource"]] = relationship(back_populates="audience")


class Tag(Base, TimestampMixin):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    color: Mapped[str] = mapped_column(String(32), default="#f2e7de")

    lead_links: Mapped[list["LeadTag"]] = relationship(back_populates="tag", cascade="all, delete-orphan")


class CampaignSource(Base, TimestampMixin):
    __tablename__ = "campaign_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255))
    start_payload: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    url: Mapped[str | None] = mapped_column(String(700), nullable=True)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    photo_count: Mapped[int] = mapped_column(Integer, default=0)
    report_count: Mapped[int] = mapped_column(Integer, default=0)
    cta_clicks: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    campaign: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    audience_id: Mapped[int | None] = mapped_column(ForeignKey("audiences.id", ondelete="SET NULL"), nullable=True)
    funnel_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assigned_manager_id: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True)
    auto_tags: Mapped[list[str]] = mapped_column(JSON, default=list)

    telegram_users: Mapped[list["TelegramUser"]] = relationship(back_populates="campaign")
    audience: Mapped[Audience | None] = relationship(back_populates="source_links")
    assigned_manager: Mapped[AdminUser | None] = relationship()


class TelegramUser(Base, TimestampMixin):
    __tablename__ = "telegram_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    language_code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    current_status: Mapped[str] = mapped_column(String(64), default=AnalysisStatus.WAITING_FOR_CONSENT)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_analysis_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rate_limit_counter: Mapped[int] = mapped_column(Integer, default=0)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaign_sources.id", ondelete="SET NULL"), nullable=True)
    start_payload: Mapped[str | None] = mapped_column(String(255), nullable=True)

    campaign: Mapped[CampaignSource | None] = relationship(back_populates="telegram_users")
    lead: Mapped["Lead | None"] = relationship(back_populates="telegram_user", cascade="all, delete-orphan")
    analyses: Mapped[list["AnalysisRequest"]] = relationship(back_populates="telegram_user", cascade="all, delete-orphan")


class Lead(Base, TimestampMixin):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(ForeignKey("telegram_users.id", ondelete="CASCADE"), unique=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(64), default=AnalysisStatus.WAITING_FOR_CONSENT, index=True)
    selected_problems: Mapped[list[str]] = mapped_column(JSON, default=list)
    report_opened: Mapped[bool] = mapped_column(Boolean, default=False)
    cta_clicked: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    utm: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    manager_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    crm_status: Mapped[str] = mapped_column(String(64), default=ClientStatus.NEW, index=True)
    first_source_link_id: Mapped[int | None] = mapped_column(ForeignKey("campaign_sources.id", ondelete="SET NULL"), nullable=True)
    last_source_link_id: Mapped[int | None] = mapped_column(ForeignKey("campaign_sources.id", ondelete="SET NULL"), nullable=True)
    audience_id: Mapped[int | None] = mapped_column(ForeignKey("audiences.id", ondelete="SET NULL"), nullable=True)
    assigned_manager_id: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)

    telegram_user: Mapped[TelegramUser] = relationship(back_populates="lead")
    analyses: Mapped[list["AnalysisRequest"]] = relationship(back_populates="lead", cascade="all, delete-orphan")
    notes: Mapped[list["AdminNote"]] = relationship(back_populates="lead", cascade="all, delete-orphan")
    audience: Mapped[Audience | None] = relationship(back_populates="leads")
    assigned_manager: Mapped[AdminUser | None] = relationship(foreign_keys=[assigned_manager_id])
    first_source_link: Mapped[CampaignSource | None] = relationship(foreign_keys=[first_source_link_id])
    last_source_link: Mapped[CampaignSource | None] = relationship(foreign_keys=[last_source_link_id])
    tag_links: Mapped[list["LeadTag"]] = relationship(back_populates="lead", cascade="all, delete-orphan")
    events: Mapped[list["LeadEvent"]] = relationship(back_populates="lead", cascade="all, delete-orphan")
    touchpoints: Mapped[list["Touchpoint"]] = relationship(back_populates="lead", cascade="all, delete-orphan")


class LeadTag(Base):
    __tablename__ = "lead_tags"
    __table_args__ = (UniqueConstraint("lead_id", "tag_id", name="uq_lead_tags_lead_tag"),)

    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    lead: Mapped[Lead] = relationship(back_populates="tag_links")
    tag: Mapped[Tag] = relationship(back_populates="lead_links")


class LeadEvent(Base):
    __tablename__ = "lead_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(120), index=True)
    title: Mapped[str] = mapped_column(String(500))
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True)

    lead: Mapped[Lead] = relationship(back_populates="events")
    created_by: Mapped[AdminUser | None] = relationship()


class Touchpoint(Base):
    __tablename__ = "touchpoints"

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    source_link_id: Mapped[int | None] = mapped_column(ForeignKey("campaign_sources.id", ondelete="SET NULL"), nullable=True, index=True)
    source: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    campaign: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    lead: Mapped[Lead] = relationship(back_populates="touchpoints")
    source_link: Mapped[CampaignSource | None] = relationship()


class AnalysisRequest(Base, TimestampMixin):
    __tablename__ = "analysis_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_user_id: Mapped[int] = mapped_column(ForeignKey("telegram_users.id", ondelete="CASCADE"), index=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(64), default=AnalysisStatus.WAITING_FOR_PHOTO, index=True)
    selected_problems: Mapped[list[str]] = mapped_column(JSON, default=list)
    original_photo_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    protocol_image_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    protocol_image_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    protocol_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    protocol_slide_paths: Mapped[list[str]] = mapped_column(JSON, default=list)
    protocol_slide_copy: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    face_protocol_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    face_protocol_image_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    protocol_copy_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    personal_insight_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    legacy_protocol_image_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    legacy_protocol_image_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    after_photo_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    after_photo_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    after_photo_plan: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    after_photo_variants: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    after_photo_variant_paths: Mapped[list[str]] = mapped_column(JSON, default=list)
    after_photo_final_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    after_photo_quality_results: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    after_photo_used_intensity: Mapped[str | None] = mapped_column(String(32), nullable=True)
    after_photo_retry_count: Mapped[int] = mapped_column(Integer, default=0)
    analysis_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    report_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    moderation_status: Mapped[str] = mapped_column(String(64), default="published")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    telegram_user: Mapped[TelegramUser] = relationship(back_populates="analyses")
    lead: Mapped[Lead] = relationship(back_populates="analyses")
    selected_problem_rows: Mapped[list["SelectedProblem"]] = relationship(back_populates="analysis", cascade="all, delete-orphan")
    zones: Mapped[list["FaceZone"]] = relationship(back_populates="analysis", cascade="all, delete-orphan")
    report: Mapped["GeneratedReport | None"] = relationship(back_populates="analysis", cascade="all, delete-orphan")
    images: Mapped[list["GeneratedImage"]] = relationship(back_populates="analysis", cascade="all, delete-orphan")
    ai_logs: Mapped[list["AiJobLog"]] = relationship(back_populates="analysis", cascade="all, delete-orphan")


class SelectedProblem(Base, TimestampMixin):
    __tablename__ = "selected_problems"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analysis_requests.id", ondelete="CASCADE"), index=True)
    slug: Mapped[str] = mapped_column(String(120), index=True)
    title: Mapped[str] = mapped_column(String(255))

    analysis: Mapped[AnalysisRequest] = relationship(back_populates="selected_problem_rows")


class FaceZone(Base, TimestampMixin):
    __tablename__ = "face_zones"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analysis_requests.id", ondelete="CASCADE"), index=True)
    number: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32))
    color: Mapped[str] = mapped_column(String(32))
    short_comment: Mapped[str] = mapped_column(String(500))
    reason: Mapped[str] = mapped_column(Text)
    recommended_focus: Mapped[str] = mapped_column(Text)

    analysis: Mapped[AnalysisRequest] = relationship(back_populates="zones")


class GeneratedReport(Base, TimestampMixin):
    __tablename__ = "generated_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analysis_requests.id", ondelete="CASCADE"), unique=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    public_token: Mapped[str] = mapped_column(String(80), unique=True, index=True, default=lambda: secrets.token_urlsafe(32))
    html_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_published: Mapped[bool] = mapped_column(Boolean, default=True)
    opened_count: Mapped[int] = mapped_column(Integer, default=0)
    cta_click_count: Mapped[int] = mapped_column(Integer, default=0)

    analysis: Mapped[AnalysisRequest] = relationship(back_populates="report")


class GeneratedImage(Base, TimestampMixin):
    __tablename__ = "generated_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int] = mapped_column(ForeignKey("analysis_requests.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(64))
    path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    negative_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(64), default="QUEUED")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    analysis: Mapped[AnalysisRequest] = relationship(back_populates="images")


class KnowledgeDocument(Base, TimestampMixin):
    __tablename__ = "knowledge_documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    filename: Mapped[str] = mapped_column(String(500))
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    chunks: Mapped[list["KnowledgeChunk"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class KnowledgeChunk(Base, TimestampMixin):
    __tablename__ = "knowledge_chunks"

    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("knowledge_documents.id", ondelete="CASCADE"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    document: Mapped[KnowledgeDocument] = relationship(back_populates="chunks")


class PromptTemplate(Base, TimestampMixin):
    __tablename__ = "prompt_templates"
    __table_args__ = (UniqueConstraint("key", name="uq_prompt_templates_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(120), index=True)
    name: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    variables: Mapped[list[str]] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class BotSettings(Base, TimestampMixin):
    __tablename__ = "bot_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    welcome_text: Mapped[str] = mapped_column(Text)
    consent_text: Mapped[str] = mapped_column(Text)
    photo_instruction_text: Mapped[str] = mapped_column(Text)
    waiting_text: Mapped[str] = mapped_column(Text)
    after_analysis_text: Mapped[str] = mapped_column(Text)
    disclaimer: Mapped[str] = mapped_column(Text)
    cta_text: Mapped[str] = mapped_column(String(255), default="Получить персональную программу")
    instagram_url: Mapped[str | None] = mapped_column(String(700), nullable=True)
    whatsapp_url: Mapped[str | None] = mapped_column(String(700), nullable=True)
    telegram_url: Mapped[str | None] = mapped_column(String(700), nullable=True)
    after_photo_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    manual_moderation_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    regeneration_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    analysis_limit_per_user: Mapped[int] = mapped_column(Integer, default=3)
    problem_catalog: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list)
    ai_settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class Broadcast(Base, TimestampMixin):
    __tablename__ = "broadcasts"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    message_type: Mapped[str] = mapped_column(String(64), default="text")
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    buttons: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list)
    audience_filter: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(64), default="draft")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    recipients: Mapped[list["BroadcastRecipient"]] = relationship(back_populates="broadcast", cascade="all, delete-orphan")


class BroadcastRecipient(Base, TimestampMixin):
    __tablename__ = "broadcast_recipients"

    id: Mapped[int] = mapped_column(primary_key=True)
    broadcast_id: Mapped[int] = mapped_column(ForeignKey("broadcasts.id", ondelete="CASCADE"), index=True)
    telegram_user_id: Mapped[int] = mapped_column(ForeignKey("telegram_users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(64), default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    broadcast: Mapped[Broadcast] = relationship(back_populates="recipients")


class EventLog(Base, TimestampMixin):
    __tablename__ = "event_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_user_id: Mapped[int | None] = mapped_column(ForeignKey("telegram_users.id", ondelete="SET NULL"), nullable=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id", ondelete="SET NULL"), nullable=True)
    event_type: Mapped[str] = mapped_column(String(120), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class AiJobLog(Base, TimestampMixin):
    __tablename__ = "ai_job_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    analysis_id: Mapped[int | None] = mapped_column(ForeignKey("analysis_requests.id", ondelete="CASCADE"), nullable=True, index=True)
    stage: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(64))
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    analysis: Mapped[AnalysisRequest | None] = relationship(back_populates="ai_logs")


class AdminNote(Base, TimestampMixin):
    __tablename__ = "admin_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    admin_id: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True)
    text: Mapped[str] = mapped_column(Text)

    lead: Mapped[Lead] = relationship(back_populates="notes")
    admin: Mapped[AdminUser | None] = relationship()


class ReportViewEvent(Base, TimestampMixin):
    __tablename__ = "report_view_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("generated_reports.id", ondelete="CASCADE"), index=True)
    ip_address: Mapped[str | None] = mapped_column(String(100), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)


class CtaClickEvent(Base, TimestampMixin):
    __tablename__ = "cta_click_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    report_id: Mapped[int] = mapped_column(ForeignKey("generated_reports.id", ondelete="CASCADE"), index=True)
    ip_address: Mapped[str | None] = mapped_column(String(100), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    target_url: Mapped[str | None] = mapped_column(String(700), nullable=True)
