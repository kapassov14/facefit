from __future__ import annotations

import csv
import io
from datetime import datetime, time, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import String, cast, func, or_
from sqlalchemy.orm import Session, selectinload

from app.api.schemas import CrmBulkAction, CrmLeadCreate, CrmLeadPatch, LeadAssign, LeadNoteCreate, LeadTagCreate, LeadTaskCreate, LeadTaskPatch
from app.core.exceptions import forbidden, not_found
from app.core.security import AdminAuth, require_write_access
from app.db.models import (
    AdminNote,
    AdminRole,
    AdminUser,
    AnalysisRequest,
    AnalysisStatus,
    Audience,
    AudienceBase,
    AudienceBaseMember,
    CampaignSource,
    ClientStatus,
    GeneratedReport,
    Lead,
    LeadActivity,
    LeadEvent,
    LeadTag,
    LeadTask,
    Tag,
    TelegramUser,
    Touchpoint,
)
from app.db.session import get_db
from app.storage.local import local_storage

router = APIRouter(prefix="/api/admin/crm", tags=["admin-crm"])


CRM_STATUS_LABELS = {
    ClientStatus.NEW: "Новый лид",
    ClientStatus.PHOTO_SENT: "Отправил фото",
    ClientStatus.PROTOCOL_SENT: "Получил протокол",
    ClientStatus.REPORT_OPENED: "Открыл отчет",
    ClientStatus.CTA_CLICKED: "Нажал CTA",
    ClientStatus.MANUAL_CONTACT: "Написать вручную",
    ClientStatus.IN_DIALOG: "В диалоге",
    ClientStatus.THINKING: "Думает",
    ClientStatus.PAID: "Оплатил",
    ClientStatus.NOT_RELEVANT: "Не актуально",
    ClientStatus.ARCHIVED: "Архив",
    ClientStatus.WARMING: "В прогреве (legacy)",
    ClientStatus.APPLIED: "Оставил заявку (legacy)",
    ClientStatus.WAITING_REPLY: "Ждет ответа (legacy)",
    ClientStatus.IN_PROGRESS: "В работе (legacy)",
    ClientStatus.BOUGHT: "Купил (legacy)",
    ClientStatus.REJECTED: "Отказ (legacy)",
    ClientStatus.NO_ANSWER: "Не отвечает (legacy)",
}

KANBAN_STATUSES = [
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

FUNNEL_EVENT_LABELS = {
    "protocol_sent": "Протокол отправлен",
    "funnel_after_visual_offer_sent": "After-оффер отправлен",
    "training_requested": "Запросили тренировку",
    "course_more_clicked": "Нажали подробнее о курсе",
    "questions_clicked": "Задали вопрос",
    "course_buy_clicked": "Нажали купить",
    "installment_clicked": "Нажали рассрочку",
    "bonuses_clicked": "Открыли бонусы",
    "funnel_offer_sent": "Оффер курса отправлен",
    "funnel_bonus_reminder_sent": "Напоминание о бонусах",
}


def _validate_status(value: str) -> str:
    if value not in CRM_STATUS_LABELS:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Неизвестный CRM-статус")
    return value


def _clean_text(value: str | None, limit: int = 255) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.strip().split())
    return cleaned[:limit] or None


def _parse_datetime(value: str | None, end_of_day: bool = False) -> datetime | None:
    if not value:
        return None
    try:
        if len(value) == 10:
            parsed = datetime.fromisoformat(value).date()
            return datetime.combine(parsed, time.max if end_of_day else time.min)
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Неверный формат даты") from exc


def _apply_period(query, column, start: datetime | None, end: datetime | None):
    if start:
        query = query.filter(column >= start)
    if end:
        query = query.filter(column <= end)
    return query


def _tag_names(lead: Lead) -> list[str]:
    result: list[str] = []
    for name in lead.tags or []:
        if name and name not in result:
            result.append(name)
    for link in lead.tag_links or []:
        if link.tag and link.tag.name not in result:
            result.append(link.tag.name)
    return result


def _tag_dicts(lead: Lead) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for link in lead.tag_links or []:
        if link.tag and link.tag.name not in seen:
            seen.add(link.tag.name)
            result.append({"id": link.tag.id, "name": link.tag.name, "color": link.tag.color})
    for name in lead.tags or []:
        if name and name not in seen:
            seen.add(name)
            result.append({"id": None, "name": name, "color": "#f2e7de"})
    return result


def _get_or_create_tag(db: Session, name: str, color: str | None = None) -> Tag:
    cleaned = _clean_text(name, 120)
    if not cleaned:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Название тега обязательно")
    tag = db.query(Tag).filter(func.lower(Tag.name) == cleaned.lower()).first()
    if tag:
        if color:
            tag.color = color
        return tag
    tag = Tag(name=cleaned, color=color or "#f2e7de")
    db.add(tag)
    db.flush()
    return tag


def _sync_lead_tags(db: Session, lead: Lead, names: list[str]) -> None:
    cleaned: list[str] = []
    for item in names:
        name = _clean_text(item, 120)
        if name and name not in cleaned:
            cleaned.append(name)
    lead.tags = cleaned
    lead.tag_links.clear()
    for name in cleaned:
        tag = _get_or_create_tag(db, name)
        lead.tag_links.append(LeadTag(tag=tag))


def _add_lead_event(
    db: Session,
    lead: Lead,
    event_type: str,
    title: str,
    metadata: dict[str, Any] | None = None,
    admin_id: int | None = None,
) -> None:
    db.add(
        LeadEvent(
            lead_id=lead.id,
            type=event_type,
            title=title,
            metadata_json=metadata or {},
            created_by_id=admin_id,
        )
    )
    db.add(
        LeadActivity(
            lead_id=lead.id,
            actor_type="manager" if admin_id else "system",
            actor_id=admin_id,
            event_type=event_type,
            payload_json={"title": title, **(metadata or {})},
        )
    )
    lead.last_activity_at = datetime.now(timezone.utc)


def _manager_dict(admin: AdminUser | None) -> dict[str, Any] | None:
    if not admin:
        return None
    return {"id": admin.id, "name": admin.name, "email": admin.email, "role": admin.role, "is_active": admin.is_active}


def _manager_report_row(db: Session, manager: AdminUser, start: datetime | None, end: datetime | None) -> dict[str, Any]:
    assigned_query = db.query(Lead).filter(Lead.assigned_manager_id == manager.id)
    assigned_leads = assigned_query.count()
    new_leads = _apply_period(assigned_query, Lead.created_at, start, end).count()

    activity_expr = func.coalesce(Lead.last_activity_at, Lead.updated_at, Lead.created_at)
    active_leads = _apply_period(
        db.query(Lead).filter(Lead.assigned_manager_id == manager.id),
        activity_expr,
        start,
        end,
    ).count()

    status_counts = {
        status_value: db.query(Lead)
        .filter(Lead.assigned_manager_id == manager.id, Lead.crm_status == status_value)
        .count()
        for status_value in CRM_STATUS_LABELS
    }
    funnel_events: dict[str, int] = {}
    for event_type in FUNNEL_EVENT_LABELS:
        event_query = (
            db.query(LeadEvent)
            .join(Lead, LeadEvent.lead_id == Lead.id)
            .filter(Lead.assigned_manager_id == manager.id, LeadEvent.type == event_type)
        )
        funnel_events[event_type] = _apply_period(event_query, LeadEvent.created_at, start, end).count()

    notes_count = _apply_period(
        db.query(AdminNote).filter(AdminNote.admin_id == manager.id),
        AdminNote.created_at,
        start,
        end,
    ).count()
    manager_events_count = _apply_period(
        db.query(LeadEvent).filter(LeadEvent.created_by_id == manager.id),
        LeadEvent.created_at,
        start,
        end,
    ).count()
    last_activity_at = assigned_query.with_entities(func.max(activity_expr)).scalar()
    applications = status_counts.get(ClientStatus.CTA_CLICKED, 0) + status_counts.get(ClientStatus.APPLIED, 0)
    purchases = status_counts.get(ClientStatus.PAID, 0) + status_counts.get(ClientStatus.BOUGHT, 0)
    return {
        "id": manager.id,
        "email": manager.email,
        "role": manager.role,
        "is_active": manager.is_active,
        "assigned_leads": assigned_leads,
        "new_leads": new_leads,
        "active_leads": active_leads,
        "status_counts": status_counts,
        "applications": applications,
        "purchases": purchases,
        "waiting_reply": status_counts.get(ClientStatus.MANUAL_CONTACT, 0) + status_counts.get(ClientStatus.WAITING_REPLY, 0),
        "in_progress": status_counts.get(ClientStatus.IN_DIALOG, 0) + status_counts.get(ClientStatus.IN_PROGRESS, 0),
        "warming": status_counts.get(ClientStatus.THINKING, 0) + status_counts.get(ClientStatus.WARMING, 0),
        "notes_count": notes_count,
        "manager_events_count": manager_events_count,
        "funnel_events": funnel_events,
        "application_conversion": round(applications / assigned_leads * 100, 2) if assigned_leads else 0,
        "purchase_conversion": round(purchases / assigned_leads * 100, 2) if assigned_leads else 0,
        "last_activity_at": last_activity_at,
    }


def _dt_key(value: datetime | None) -> datetime:
    if not value:
        return datetime.min
    return value.replace(tzinfo=None) if value.tzinfo else value


def _is_overdue(value: datetime | None) -> bool:
    if not value:
        return False
    now = datetime.now(value.tzinfo) if value.tzinfo else datetime.now()
    return value < now


def _can_access_lead(admin: AdminUser, lead: Lead) -> bool:
    if admin.role in {AdminRole.OWNER, AdminRole.ADMIN, AdminRole.VIEWER}:
        return True
    return lead.assigned_manager_id == admin.id


def _source_link_dict(link: CampaignSource | None) -> dict[str, Any] | None:
    if not link:
        return None
    return {
        "id": link.id,
        "name": link.title,
        "slug": link.slug,
        "full_url": link.url,
        "source": link.source,
        "campaign": link.campaign,
        "is_active": link.is_active,
    }


def _media_url(path: str | None) -> str | None:
    if not path:
        return None
    if path.startswith("http") or path.startswith("/api/"):
        return path
    return local_storage.public_url(path)


def _crm_lead_dict(lead: Lead, include_detail: bool = False) -> dict[str, Any]:
    events = sorted(lead.events or [], key=lambda item: _dt_key(item.created_at), reverse=True)
    activities = sorted(getattr(lead, "activities", []) or [], key=lambda item: _dt_key(item.created_at), reverse=True)
    touchpoints = sorted(lead.touchpoints or [], key=lambda item: _dt_key(item.created_at), reverse=True)
    latest_event = events[0] if events else None
    latest_activity = activities[0] if activities else None
    latest_analysis = sorted(lead.analyses or [], key=lambda item: _dt_key(item.created_at), reverse=True)[0] if lead.analyses else None
    report = latest_analysis.report if latest_analysis and latest_analysis.report else None
    telegram_user = lead.telegram_user
    full_name = lead.name or " ".join(
        item for item in [telegram_user.first_name if telegram_user else None, telegram_user.last_name if telegram_user else None] if item
    )
    first_link = lead.first_source_link
    last_link = lead.last_source_link
    source = lead.source or (last_link.source if last_link else None) or (first_link.source if first_link else None)
    campaign = (last_link.campaign if last_link else None) or (first_link.campaign if first_link else None)
    data: dict[str, Any] = {
        "id": lead.id,
        "name": full_name or None,
        "phone": lead.phone,
        "status": lead.crm_status or ClientStatus.NEW,
        "technical_status": lead.status,
        "selected_problems": lead.selected_problems or [],
        "tags": _tag_dicts(lead),
        "tag_names": _tag_names(lead),
        "source": source,
        "campaign": campaign,
        "audience": {"id": lead.audience.id, "name": lead.audience.name, "color": lead.audience.color} if lead.audience else None,
        "assigned_manager": _manager_dict(lead.assigned_manager),
        "assigned_at": lead.assigned_at,
        "assigned_by": _manager_dict(lead.assigned_by),
        "manager_comment": lead.manager_comment,
        "first_source_link": _source_link_dict(first_link),
        "last_source_link": _source_link_dict(last_link),
        "created_at": lead.created_at,
        "updated_at": lead.updated_at,
        "last_activity_at": lead.last_activity_at or lead.updated_at,
        "last_action": latest_event.title if latest_event else None,
        "touch_count": len(events) + len(touchpoints) + len(lead.notes or []) + len(activities),
        "report_opened": lead.report_opened,
        "cta_clicked": lead.cta_clicked,
        "after_photo_status": latest_analysis.after_photo_status if latest_analysis else None,
        "has_after_photo": bool(latest_analysis and (latest_analysis.after_photo_final_path or latest_analysis.after_photo_path)),
        "report": {
            "id": report.id,
            "public_token": report.public_token,
            "url": f"/report/{report.public_token}",
            "opened_count": report.opened_count,
            "cta_click_count": report.cta_click_count,
            "is_published": report.is_published,
        }
        if report
        else None,
        "bases": [
            {"id": membership.base.id, "name": membership.base.name, "type": membership.base.type, "added_at": membership.added_at}
            for membership in (lead.base_memberships or [])
            if membership.base
        ],
        "tasks_count": len([task for task in (lead.tasks or []) if task.status == "todo"]),
        "overdue_tasks_count": len(
            [
                task
                for task in (lead.tasks or [])
                if task.status == "todo" and _is_overdue(task.due_at)
            ]
        ),
        "urgency": "high"
        if lead.cta_clicked or any(task.status == "todo" and _is_overdue(task.due_at) for task in (lead.tasks or []))
        else ("medium" if lead.report_opened else "normal"),
        "telegram_user": {
            "id": telegram_user.id,
            "telegram_id": telegram_user.telegram_id,
            "username": telegram_user.username,
            "first_name": telegram_user.first_name,
            "last_name": telegram_user.last_name,
            "language_code": telegram_user.language_code,
            "is_blocked": telegram_user.is_blocked,
            "unsubscribed": telegram_user.unsubscribed,
            "last_bot_interaction_at": telegram_user.last_bot_interaction_at,
            "last_message_sent_at": telegram_user.last_message_sent_at,
            "last_message_error": telegram_user.last_message_error,
        }
        if telegram_user
        else None,
    }
    if include_detail:
        data["events"] = [
            {
                "id": event.id,
                "type": event.type,
                "title": event.title,
                "metadata": event.metadata_json or {},
                "created_at": event.created_at,
                "created_by": _manager_dict(event.created_by),
            }
            for event in events
        ]
        data["activities"] = [
            {
                "id": item.id,
                "actor_type": item.actor_type,
                "actor": _manager_dict(item.actor),
                "event_type": item.event_type,
                "payload": item.payload_json or {},
                "created_at": item.created_at,
            }
            for item in activities
        ]
        data["touchpoints"] = [
            {
                "id": item.id,
                "source": item.source,
                "campaign": item.campaign,
                "payload": item.payload or {},
                "source_link": _source_link_dict(item.source_link),
                "created_at": item.created_at,
            }
            for item in touchpoints
        ]
        data["notes"] = [
            {
                "id": note.id,
                "text": note.text,
                "created_at": note.created_at,
                "author": _manager_dict(note.admin),
            }
            for note in sorted(lead.notes or [], key=lambda item: _dt_key(item.created_at), reverse=True)
        ]
        data["analyses"] = [
            {
                "id": item.id,
                "status": item.status,
                "created_at": item.created_at,
                "selected_problems": item.selected_problems or [],
                "original_photo_url": _media_url(item.original_photo_path),
                "face_protocol_image_url": _media_url(item.face_protocol_image_path or item.protocol_image_path or item.legacy_protocol_image_path),
                "protocol_image_url": _media_url(item.face_protocol_image_path or item.protocol_image_path or item.legacy_protocol_image_path),
                "after_photo_status": item.after_photo_status,
                "after_photo_url": _media_url(item.after_photo_final_path or item.after_photo_path),
                "report_public_token": item.report.public_token if item.report else None,
            }
            for item in sorted(lead.analyses or [], key=lambda item: item.created_at, reverse=True)
        ]
        data["tasks"] = [
            {
                "id": task.id,
                "title": task.title,
                "description": task.description,
                "due_at": task.due_at,
                "status": task.status,
                "assigned_to": _manager_dict(task.assigned_to),
                "created_by": _manager_dict(task.created_by),
                "created_at": task.created_at,
                "completed_at": task.completed_at,
            }
            for task in sorted(lead.tasks or [], key=lambda item: _dt_key(item.due_at or item.created_at))
        ]
        data["media"] = {
            "original_photo_url": _media_url(latest_analysis.original_photo_path if latest_analysis else None),
            "face_protocol_image_url": _media_url(
                (latest_analysis.face_protocol_image_path or latest_analysis.protocol_image_path or latest_analysis.legacy_protocol_image_path)
                if latest_analysis
                else None
            ),
            "after_photo_url": _media_url((latest_analysis.after_photo_final_path or latest_analysis.after_photo_path) if latest_analysis else None),
        }
    return data


def _lead_options_query(db: Session):
    return db.query(Lead).options(
        selectinload(Lead.telegram_user),
        selectinload(Lead.audience),
        selectinload(Lead.assigned_manager),
        selectinload(Lead.first_source_link),
        selectinload(Lead.last_source_link),
        selectinload(Lead.tag_links).selectinload(LeadTag.tag),
        selectinload(Lead.events).selectinload(LeadEvent.created_by),
        selectinload(Lead.activities).selectinload(LeadActivity.actor),
        selectinload(Lead.touchpoints).selectinload(Touchpoint.source_link),
        selectinload(Lead.notes).selectinload(AdminNote.admin),
        selectinload(Lead.tasks).selectinload(LeadTask.assigned_to),
        selectinload(Lead.tasks).selectinload(LeadTask.created_by),
        selectinload(Lead.base_memberships).selectinload(AudienceBaseMember.base),
        selectinload(Lead.analyses).selectinload(AnalysisRequest.report),
    )


def _apply_lead_filters(
    query,
    db: Session,
    search: str | None = None,
    status_value: str | None = None,
    tag: str | None = None,
    source: str | None = None,
    source_link_id: int | None = None,
    audience_id: int | None = None,
    base_id: int | None = None,
    manager_id: int | None = None,
    problem: str | None = None,
    report_opened: bool | None = None,
    cta_clicked: bool | None = None,
    after_photo_status: str | None = None,
    only_mine: bool = False,
    unassigned: bool = False,
    current_admin_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    activity_from: str | None = None,
    activity_to: str | None = None,
):
    if search:
        like = f"%{search.strip()}%"
        query = query.join(TelegramUser).filter(
            or_(
                Lead.name.ilike(like),
                Lead.phone.ilike(like),
                TelegramUser.username.ilike(like),
                TelegramUser.first_name.ilike(like),
                TelegramUser.last_name.ilike(like),
                cast(TelegramUser.telegram_id, String).ilike(like),
            )
        )
    if status_value:
        query = query.filter(Lead.crm_status == _validate_status(status_value))
    if tag:
        like = f"%{tag.strip()}%"
        if db.bind and db.bind.dialect.name == "postgresql":
            query = query.filter(Lead.tags.contains([tag]))
        else:
            query = query.filter(cast(Lead.tags, String).ilike(like))
    if source:
        query = query.filter(or_(Lead.source == source, Lead.last_source_link.has(CampaignSource.source == source)))
    if source_link_id:
        query = query.filter(or_(Lead.first_source_link_id == source_link_id, Lead.last_source_link_id == source_link_id))
    if audience_id:
        query = query.filter(Lead.audience_id == audience_id)
    if base_id:
        query = query.filter(Lead.base_memberships.any(AudienceBaseMember.base_id == base_id))
    if manager_id:
        query = query.filter(Lead.assigned_manager_id == manager_id)
    if only_mine and current_admin_id:
        query = query.filter(Lead.assigned_manager_id == current_admin_id)
    if unassigned:
        query = query.filter(Lead.assigned_manager_id.is_(None))
    if problem:
        like = f"%{problem.strip()}%"
        if db.bind and db.bind.dialect.name == "postgresql":
            query = query.filter(Lead.selected_problems.contains([problem]))
        else:
            query = query.filter(cast(Lead.selected_problems, String).ilike(like))
    if report_opened is not None:
        query = query.filter(Lead.report_opened.is_(report_opened))
    if cta_clicked is not None:
        query = query.filter(Lead.cta_clicked.is_(cta_clicked))
    if after_photo_status:
        query = query.filter(Lead.analyses.any(AnalysisRequest.after_photo_status == after_photo_status))
    created_from = _parse_datetime(date_from)
    created_to = _parse_datetime(date_to, end_of_day=True)
    if created_from:
        query = query.filter(Lead.created_at >= created_from)
    if created_to:
        query = query.filter(Lead.created_at <= created_to)
    activity_expr = func.coalesce(Lead.last_activity_at, Lead.updated_at, Lead.created_at)
    active_from = _parse_datetime(activity_from)
    active_to = _parse_datetime(activity_to, end_of_day=True)
    if active_from:
        query = query.filter(activity_expr >= active_from)
    if active_to:
        query = query.filter(activity_expr <= active_to)
    return query


@router.get("/stats")
def crm_stats(_: AdminAuth, db: Session = Depends(get_db)) -> dict:
    now = datetime.now(timezone.utc)
    today = now.date()
    seven_days_ago = now - timedelta(days=7)
    total = db.query(Lead).count()
    new_today = db.query(Lead).filter(func.date(Lead.created_at) == today).count()
    new_7_days = db.query(Lead).filter(Lead.created_at >= seven_days_ago).count()
    applications = db.query(Lead).filter(Lead.crm_status.in_([ClientStatus.CTA_CLICKED, ClientStatus.APPLIED])).count()
    purchases = db.query(Lead).filter(Lead.crm_status.in_([ClientStatus.PAID, ClientStatus.BOUGHT])).count()
    source_rows = (
        db.query(Lead.source, func.count(Lead.id).label("count"))
        .filter(Lead.source.is_not(None))
        .group_by(Lead.source)
        .order_by(func.count(Lead.id).desc())
        .limit(1)
        .all()
    )
    best_source = {"source": source_rows[0][0], "count": source_rows[0][1]} if source_rows else None
    return {
        "total": total,
        "new_today": new_today,
        "new_7_days": new_7_days,
        "applications": applications,
        "purchases": purchases,
        "application_conversion": round(applications / total * 100, 2) if total else 0,
        "purchase_conversion": round(purchases / total * 100, 2) if total else 0,
        "best_source": best_source,
    }


@router.get("/options")
def crm_options(_: AdminAuth, db: Session = Depends(get_db)) -> dict:
    return {
        "statuses": [{"value": value, "label": label} for value, label in CRM_STATUS_LABELS.items()],
        "audiences": [
            {"id": item.id, "name": item.name, "color": item.color}
            for item in db.query(Audience).order_by(Audience.name.asc()).all()
        ],
        "bases": [
            {"id": item.id, "name": item.name, "type": item.type}
            for item in db.query(AudienceBase).order_by(AudienceBase.name.asc()).all()
        ],
        "tags": [{"id": item.id, "name": item.name, "color": item.color} for item in db.query(Tag).order_by(Tag.name.asc()).all()],
        "managers": [
            {"id": item.id, "email": item.email, "role": item.role}
            for item in db.query(AdminUser)
            .filter(AdminUser.is_active.is_(True), AdminUser.role.in_([AdminRole.OWNER, AdminRole.ADMIN, AdminRole.MANAGER]))
            .order_by(AdminUser.email.asc())
            .all()
        ],
        "links": [
            {"id": item.id, "name": item.title, "source": item.source, "campaign": item.campaign}
            for item in db.query(CampaignSource).order_by(CampaignSource.created_at.desc()).all()
        ],
    }


@router.get("/managers/report")
def manager_report(
    _: AdminAuth,
    db: Session = Depends(get_db),
    date_from: str | None = None,
    date_to: str | None = None,
    manager_id: int | None = None,
) -> dict:
    start = _parse_datetime(date_from)
    end = _parse_datetime(date_to, end_of_day=True)
    managers_query = db.query(AdminUser).filter(AdminUser.role.in_([AdminRole.OWNER, AdminRole.MANAGER]))
    if manager_id:
        managers_query = managers_query.filter(AdminUser.id == manager_id)
    managers = managers_query.order_by(AdminUser.is_active.desc(), AdminUser.email.asc()).all()
    items = [_manager_report_row(db, manager, start, end) for manager in managers]
    numeric_keys = [
        "assigned_leads",
        "new_leads",
        "active_leads",
        "applications",
        "purchases",
        "waiting_reply",
        "in_progress",
        "warming",
        "notes_count",
        "manager_events_count",
    ]
    totals: dict[str, Any] = {key: sum(int(item.get(key) or 0) for item in items) for key in numeric_keys}
    totals["funnel_events"] = {
        event_type: sum(int(item["funnel_events"].get(event_type) or 0) for item in items) for event_type in FUNNEL_EVENT_LABELS
    }
    totals["application_conversion"] = round(totals["applications"] / totals["assigned_leads"] * 100, 2) if totals["assigned_leads"] else 0
    totals["purchase_conversion"] = round(totals["purchases"] / totals["assigned_leads"] * 100, 2) if totals["assigned_leads"] else 0
    return {
        "items": items,
        "totals": totals,
        "funnel_event_labels": FUNNEL_EVENT_LABELS,
        "date_from": date_from,
        "date_to": date_to,
    }


@router.get("/leads")
def list_crm_leads(
    admin: AdminAuth,
    db: Session = Depends(get_db),
    search: str | None = None,
    status: str | None = None,
    tag: str | None = None,
    source: str | None = None,
    source_link_id: int | None = None,
    audience_id: int | None = None,
    base_id: int | None = None,
    manager_id: int | None = None,
    problem: str | None = None,
    report_opened: bool | None = None,
    cta_clicked: bool | None = None,
    after_photo_status: str | None = None,
    only_mine: bool = False,
    unassigned: bool = False,
    date_from: str | None = None,
    date_to: str | None = None,
    activity_from: str | None = None,
    activity_to: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    limit: int | None = Query(None, le=100),
    offset: int = Query(0, ge=0),
) -> dict:
    if admin.role == AdminRole.MANAGER:
        only_mine = True
    effective_limit = limit or page_size
    effective_offset = offset if limit is not None else (page - 1) * effective_limit
    query = _apply_lead_filters(
        _lead_options_query(db),
        db,
        search=search,
        status_value=status,
        tag=tag,
        source=source,
        source_link_id=source_link_id,
        audience_id=audience_id,
        base_id=base_id,
        manager_id=manager_id,
        problem=problem,
        report_opened=report_opened,
        cta_clicked=cta_clicked,
        after_photo_status=after_photo_status,
        only_mine=only_mine,
        unassigned=unassigned,
        current_admin_id=admin.id,
        date_from=date_from,
        date_to=date_to,
        activity_from=activity_from,
        activity_to=activity_to,
    )
    total = query.count()
    activity_expr = func.coalesce(Lead.last_activity_at, Lead.updated_at, Lead.created_at)
    items = query.order_by(activity_expr.desc()).offset(effective_offset).limit(effective_limit).all()
    return {
        "items": [_crm_lead_dict(item) for item in items],
        "total": total,
        "limit": effective_limit,
        "offset": effective_offset,
        "page": page,
        "page_size": effective_limit,
    }


@router.get("/kanban")
def crm_kanban(
    admin: AdminAuth,
    db: Session = Depends(get_db),
    search: str | None = None,
    tag: str | None = None,
    source: str | None = None,
    source_link_id: int | None = None,
    audience_id: int | None = None,
    base_id: int | None = None,
    manager_id: int | None = None,
    problem: str | None = None,
    report_opened: bool | None = None,
    cta_clicked: bool | None = None,
    after_photo_status: str | None = None,
    only_mine: bool = False,
    unassigned: bool = False,
    date_from: str | None = None,
    date_to: str | None = None,
    activity_from: str | None = None,
    activity_to: str | None = None,
    limit_per_status: int = Query(50, ge=1, le=100),
) -> dict:
    if admin.role == AdminRole.MANAGER:
        only_mine = True
    activity_expr = func.coalesce(Lead.last_activity_at, Lead.updated_at, Lead.created_at)
    sections = []
    for status_value in KANBAN_STATUSES:
        query = _apply_lead_filters(
            _lead_options_query(db),
            db,
            search=search,
            status_value=status_value,
            tag=tag,
            source=source,
            source_link_id=source_link_id,
            audience_id=audience_id,
            base_id=base_id,
            manager_id=manager_id,
            problem=problem,
            report_opened=report_opened,
            cta_clicked=cta_clicked,
            after_photo_status=after_photo_status,
            only_mine=only_mine,
            unassigned=unassigned,
            current_admin_id=admin.id,
            date_from=date_from,
            date_to=date_to,
            activity_from=activity_from,
            activity_to=activity_to,
        )
        total = query.count()
        items = query.order_by(activity_expr.desc()).limit(limit_per_status).all()
        sections.append(
            {
                "status": status_value,
                "label": CRM_STATUS_LABELS[status_value],
                "total": total,
                "items": [_crm_lead_dict(item) for item in items],
            }
        )
    return {"statuses": [{"value": value, "label": CRM_STATUS_LABELS[value]} for value in KANBAN_STATUSES], "sections": sections}


@router.post("/leads")
def create_crm_lead(payload: CrmLeadCreate, admin: AdminAuth, db: Session = Depends(get_db)) -> dict:
    require_write_access(admin)
    _validate_status(payload.status)
    telegram_user = db.query(TelegramUser).filter(TelegramUser.telegram_id == payload.telegram_id).first()
    if telegram_user and telegram_user.lead:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Клиент с таким Telegram ID уже существует")
    if not telegram_user:
        telegram_user = TelegramUser(
            telegram_id=payload.telegram_id,
            username=_clean_text(payload.username),
            first_name=_clean_text(payload.first_name),
            last_name=_clean_text(payload.last_name),
            current_status=AnalysisStatus.WAITING_FOR_CONSENT,
        )
        db.add(telegram_user)
        db.flush()
    lead = Lead(
        telegram_user_id=telegram_user.id,
        name=_clean_text(payload.name),
        phone=_clean_text(payload.phone, 64),
        crm_status=payload.status,
        source=_clean_text(payload.source),
        audience_id=payload.audience_id,
        assigned_manager_id=payload.assigned_manager_id,
        assigned_at=datetime.now(timezone.utc) if payload.assigned_manager_id else None,
        assigned_by_id=admin.id if payload.assigned_manager_id else None,
        last_activity_at=datetime.now(timezone.utc),
    )
    db.add(lead)
    db.flush()
    _sync_lead_tags(db, lead, payload.tags)
    _add_lead_event(db, lead, "created", "Клиент создан вручную", {"source": "admin"}, admin.id)
    db.commit()
    db.refresh(lead)
    return _crm_lead_dict(lead)


@router.get("/leads/export")
def export_crm_leads(
    admin: AdminAuth,
    db: Session = Depends(get_db),
    ids: str | None = None,
    search: str | None = None,
    status: str | None = None,
    tag: str | None = None,
    source: str | None = None,
    source_link_id: int | None = None,
    audience_id: int | None = None,
    base_id: int | None = None,
    manager_id: int | None = None,
    problem: str | None = None,
    report_opened: bool | None = None,
    cta_clicked: bool | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    activity_from: str | None = None,
    activity_to: str | None = None,
) -> StreamingResponse:
    only_mine = admin.role == AdminRole.MANAGER
    query = _apply_lead_filters(
        _lead_options_query(db),
        db,
        search=search,
        status_value=status,
        tag=tag,
        source=source,
        source_link_id=source_link_id,
        audience_id=audience_id,
        base_id=base_id,
        manager_id=manager_id,
        problem=problem,
        report_opened=report_opened,
        cta_clicked=cta_clicked,
        only_mine=only_mine,
        current_admin_id=admin.id,
        date_from=date_from,
        date_to=date_to,
        activity_from=activity_from,
        activity_to=activity_to,
    )
    if ids:
        selected_ids = [int(item) for item in ids.split(",") if item.strip().isdigit()]
        query = query.filter(Lead.id.in_(selected_ids))
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["name", "username", "telegramId", "phone", "status", "source", "campaign", "linkName", "audience", "tags", "manager", "createdAt", "lastActivityAt"])
    for lead in query.order_by(Lead.created_at.desc()).all():
        row = _crm_lead_dict(lead)
        writer.writerow(
            [
                row["name"] or "",
                row["telegram_user"]["username"] if row["telegram_user"] else "",
                row["telegram_user"]["telegram_id"] if row["telegram_user"] else "",
                row["phone"] or "",
                CRM_STATUS_LABELS.get(row["status"], row["status"]),
                row["source"] or "",
                row["campaign"] or "",
                row["last_source_link"]["name"] if row["last_source_link"] else "",
                row["audience"]["name"] if row["audience"] else "",
                "; ".join(row["tag_names"]),
                row["assigned_manager"]["email"] if row["assigned_manager"] else "",
                row["created_at"],
                row["last_activity_at"],
            ]
        )
    output.seek(0)
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=crm_leads.csv"})


@router.get("/leads/{lead_id}")
def get_crm_lead(lead_id: int, admin: AdminAuth, db: Session = Depends(get_db)) -> dict:
    lead = _lead_options_query(db).filter(Lead.id == lead_id).first()
    if not lead:
        raise not_found("Клиент не найден")
    if not _can_access_lead(admin, lead):
        raise forbidden()
    return _crm_lead_dict(lead, include_detail=True)


@router.patch("/leads/{lead_id}")
def patch_crm_lead(lead_id: int, payload: CrmLeadPatch, admin: AdminAuth, db: Session = Depends(get_db)) -> dict:
    require_write_access(admin)
    lead = _lead_options_query(db).filter(Lead.id == lead_id).first()
    if not lead:
        raise not_found("Клиент не найден")
    if not _can_access_lead(admin, lead):
        raise forbidden()
    data = payload.model_dump(exclude_unset=True)
    if "status" in data and data["status"] is not None:
        previous = lead.crm_status
        lead.crm_status = _validate_status(data["status"])
        if previous != lead.crm_status:
            _add_lead_event(
                db,
                lead,
                "status_changed",
                f"Статус изменен: {CRM_STATUS_LABELS.get(lead.crm_status, lead.crm_status)}",
                {"from": previous, "to": lead.crm_status},
                admin.id,
            )
    for field in ["name", "phone", "source", "manager_comment"]:
        if field in data:
            setattr(lead, field, _clean_text(data[field], 64 if field == "phone" else 255))
    if "audience_id" in data:
        lead.audience_id = data["audience_id"]
        _add_lead_event(db, lead, "audience_changed", "Клиент перемещен в другую базу", {"audience_id": lead.audience_id}, admin.id)
    if "assigned_manager_id" in data:
        lead.assigned_manager_id = data["assigned_manager_id"]
        lead.assigned_at = datetime.now(timezone.utc) if data["assigned_manager_id"] else None
        lead.assigned_by_id = admin.id if data["assigned_manager_id"] else None
        _add_lead_event(db, lead, "manager_assigned", "Назначен ответственный менеджер", {"manager_id": lead.assigned_manager_id}, admin.id)
    if "tags" in data and data["tags"] is not None:
        _sync_lead_tags(db, lead, data["tags"])
        _add_lead_event(db, lead, "tags_changed", "Обновлены теги клиента", {"tags": data["tags"]}, admin.id)
    lead.last_activity_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(lead)
    return _crm_lead_dict(lead, include_detail=True)


@router.post("/leads/{lead_id}/notes")
def add_lead_note(lead_id: int, payload: LeadNoteCreate, admin: AdminAuth, db: Session = Depends(get_db)) -> dict:
    require_write_access(admin)
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise not_found("Клиент не найден")
    if not _can_access_lead(admin, lead):
        raise forbidden()
    note = AdminNote(lead_id=lead.id, admin_id=admin.id, text=payload.text.strip())
    db.add(note)
    db.flush()
    _add_lead_event(db, lead, "note_added", "Добавлена заметка менеджера", {"note_id": note.id}, admin.id)
    lead.last_activity_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(note)
    return {"id": note.id, "text": note.text, "created_at": note.created_at, "author": _manager_dict(admin)}


@router.post("/leads/{lead_id}/tags")
def add_lead_tag(lead_id: int, payload: LeadTagCreate, admin: AdminAuth, db: Session = Depends(get_db)) -> dict:
    require_write_access(admin)
    lead = _lead_options_query(db).filter(Lead.id == lead_id).first()
    if not lead:
        raise not_found("Клиент не найден")
    if not _can_access_lead(admin, lead):
        raise forbidden()
    if payload.tag_id:
        tag = db.query(Tag).filter(Tag.id == payload.tag_id).first()
        if not tag:
            raise not_found("Тег не найден")
    else:
        tag = _get_or_create_tag(db, payload.name or "", payload.color)
    if tag.name not in (lead.tags or []):
        lead.tags = [*(lead.tags or []), tag.name]
    if not any(link.tag_id == tag.id for link in lead.tag_links):
        lead.tag_links.append(LeadTag(tag=tag))
    _add_lead_event(db, lead, "tag_added", f"Добавлен тег {tag.name}", {"tag_id": tag.id, "tag": tag.name}, admin.id)
    lead.last_activity_at = datetime.now(timezone.utc)
    db.commit()
    return _crm_lead_dict(lead, include_detail=True)


@router.delete("/leads/{lead_id}/tags/{tag_id}")
def remove_lead_tag(lead_id: int, tag_id: int, admin: AdminAuth, db: Session = Depends(get_db)) -> dict:
    require_write_access(admin)
    lead = _lead_options_query(db).filter(Lead.id == lead_id).first()
    if not lead:
        raise not_found("Клиент не найден")
    if not _can_access_lead(admin, lead):
        raise forbidden()
    tag = db.query(Tag).filter(Tag.id == tag_id).first()
    if not tag:
        raise not_found("Тег не найден")
    lead.tags = [name for name in (lead.tags or []) if name != tag.name]
    for link in list(lead.tag_links):
        if link.tag_id == tag.id:
            lead.tag_links.remove(link)
    _add_lead_event(db, lead, "tag_removed", f"Удален тег {tag.name}", {"tag_id": tag.id, "tag": tag.name}, admin.id)
    lead.last_activity_at = datetime.now(timezone.utc)
    db.commit()
    return _crm_lead_dict(lead, include_detail=True)


@router.post("/leads/{lead_id}/assign")
def assign_lead(lead_id: int, payload: LeadAssign, admin: AdminAuth, db: Session = Depends(get_db)) -> dict:
    require_write_access(admin)
    lead = _lead_options_query(db).filter(Lead.id == lead_id).first()
    if not lead:
        raise not_found("Клиент не найден")
    if not _can_access_lead(admin, lead):
        raise forbidden()
    if payload.manager_id:
        manager = db.query(AdminUser).filter(AdminUser.id == payload.manager_id, AdminUser.is_active.is_(True)).first()
        if not manager:
            raise not_found("Менеджер не найден")
    lead.assigned_manager_id = payload.manager_id
    lead.assigned_at = datetime.now(timezone.utc) if payload.manager_id else None
    lead.assigned_by_id = admin.id if payload.manager_id else None
    _add_lead_event(db, lead, "manager_assigned", "Назначен ответственный менеджер", {"manager_id": payload.manager_id}, admin.id)
    db.commit()
    db.refresh(lead)
    return _crm_lead_dict(lead, include_detail=True)


@router.post("/leads/{lead_id}/tasks")
def create_lead_task(lead_id: int, payload: LeadTaskCreate, admin: AdminAuth, db: Session = Depends(get_db)) -> dict:
    require_write_access(admin)
    lead = _lead_options_query(db).filter(Lead.id == lead_id).first()
    if not lead:
        raise not_found("Клиент не найден")
    if not _can_access_lead(admin, lead):
        raise forbidden()
    due_at = _parse_datetime(payload.due_at) if payload.due_at else None
    task = LeadTask(
        lead_id=lead.id,
        assigned_to_id=payload.assigned_to_id or lead.assigned_manager_id or admin.id,
        title=payload.title.strip(),
        description=payload.description,
        due_at=due_at,
        status="todo",
        created_by_id=admin.id,
    )
    db.add(task)
    db.flush()
    _add_lead_event(db, lead, "task_created", "Создана задача", {"task_id": task.id, "title": task.title}, admin.id)
    db.commit()
    db.refresh(task)
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "due_at": task.due_at,
        "status": task.status,
        "assigned_to": _manager_dict(task.assigned_to),
        "created_at": task.created_at,
    }


@router.patch("/leads/{lead_id}/tasks/{task_id}")
def patch_lead_task(lead_id: int, task_id: int, payload: LeadTaskPatch, admin: AdminAuth, db: Session = Depends(get_db)) -> dict:
    require_write_access(admin)
    lead = _lead_options_query(db).filter(Lead.id == lead_id).first()
    if not lead:
        raise not_found("Клиент не найден")
    if not _can_access_lead(admin, lead):
        raise forbidden()
    task = db.query(LeadTask).filter(LeadTask.id == task_id, LeadTask.lead_id == lead.id).first()
    if not task:
        raise not_found("Задача не найдена")
    data = payload.model_dump(exclude_unset=True)
    if data.get("title") is not None:
        task.title = data["title"].strip()
    if "description" in data:
        task.description = data["description"]
    if "due_at" in data:
        task.due_at = _parse_datetime(data["due_at"]) if data["due_at"] else None
    if "assigned_to_id" in data:
        task.assigned_to_id = data["assigned_to_id"]
    if data.get("status") is not None:
        if data["status"] not in {"todo", "done", "cancelled"}:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Неизвестный статус задачи")
        task.status = data["status"]
        task.completed_at = datetime.now(timezone.utc) if task.status == "done" else None
        _add_lead_event(db, lead, "task_updated", "Обновлена задача", {"task_id": task.id, "status": task.status}, admin.id)
    db.commit()
    db.refresh(task)
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "due_at": task.due_at,
        "status": task.status,
        "assigned_to": _manager_dict(task.assigned_to),
        "completed_at": task.completed_at,
    }


@router.post("/leads/bulk-action")
def crm_bulk_action(payload: CrmBulkAction, admin: AdminAuth, db: Session = Depends(get_db)) -> dict:
    require_write_access(admin)
    if not payload.lead_ids:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Не выбраны лиды")
    leads = _lead_options_query(db).filter(Lead.id.in_(payload.lead_ids)).all()
    changed = 0
    for lead in leads:
        if not _can_access_lead(admin, lead):
            continue
        if payload.action == "set_status":
            if not payload.status:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Нужен status")
            previous = lead.crm_status
            lead.crm_status = _validate_status(payload.status)
            _add_lead_event(db, lead, "status_changed", "Статус изменен bulk-действием", {"from": previous, "to": lead.crm_status}, admin.id)
        elif payload.action == "assign_manager":
            lead.assigned_manager_id = payload.manager_id
            lead.assigned_at = datetime.now(timezone.utc) if payload.manager_id else None
            lead.assigned_by_id = admin.id if payload.manager_id else None
            _add_lead_event(db, lead, "manager_assigned", "Назначен менеджер bulk-действием", {"manager_id": payload.manager_id}, admin.id)
        elif payload.action == "add_tag":
            if not payload.tag:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Нужен tag")
            _sync_lead_tags(db, lead, [*(_tag_names(lead)), payload.tag])
            _add_lead_event(db, lead, "tag_added", "Добавлен тег bulk-действием", {"tag": payload.tag}, admin.id)
        elif payload.action == "add_to_base":
            if not payload.base_id:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Нужен base_id")
            base = db.query(AudienceBase).filter(AudienceBase.id == payload.base_id).first()
            if not base:
                raise not_found("База не найдена")
            exists = db.query(AudienceBaseMember).filter(AudienceBaseMember.base_id == base.id, AudienceBaseMember.lead_id == lead.id).first()
            if not exists:
                db.add(AudienceBaseMember(base_id=base.id, lead_id=lead.id, telegram_user_id=lead.telegram_user_id, added_by_id=admin.id))
                _add_lead_event(db, lead, "base_added", "Добавлен в базу", {"base_id": base.id}, admin.id)
        elif payload.action == "remove_from_base":
            if not payload.base_id:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Нужен base_id")
            db.query(AudienceBaseMember).filter(AudienceBaseMember.base_id == payload.base_id, AudienceBaseMember.lead_id == lead.id).delete()
            _add_lead_event(db, lead, "base_removed", "Удален из базы", {"base_id": payload.base_id}, admin.id)
        elif payload.action == "archive":
            previous = lead.crm_status
            lead.crm_status = ClientStatus.ARCHIVED
            _add_lead_event(db, lead, "status_changed", "Лид отправлен в архив", {"from": previous, "to": ClientStatus.ARCHIVED}, admin.id)
        else:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Неизвестное bulk-действие")
        lead.last_activity_at = datetime.now(timezone.utc)
        changed += 1
    db.commit()
    return {"ok": True, "changed": changed}
