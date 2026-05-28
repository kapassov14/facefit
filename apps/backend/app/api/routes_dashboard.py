from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import String, cast, func, or_
from sqlalchemy.orm import Session, selectinload

from app.core.security import AdminAuth
from app.db.models import (
    AiJobLog,
    AnalysisRequest,
    AnalysisStatus,
    AudienceBase,
    AudienceBaseMember,
    BroadcastRecipient,
    ClientStatus,
    CtaClickEvent,
    EventLog,
    GeneratedReport,
    Lead,
    LeadEvent,
    ReportViewEvent,
    SelectedProblem,
    TelegramUser,
)
from app.db.session import get_db

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])
admin_router = APIRouter(prefix="/api/admin/dashboard", tags=["admin-dashboard"])


TERMINAL_CRM_STATUSES = {ClientStatus.PAID, ClientStatus.NOT_RELEVANT, ClientStatus.ARCHIVED}


def _parse_date(value: str | None, end_of_day: bool = False) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if len(value) == 10:
            return datetime.combine(parsed.date(), time.max if end_of_day else time.min)
        return parsed
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Неверный формат даты") from exc


def _period_range(period: str = "7d", date_from: str | None = None, date_to: str | None = None) -> tuple[datetime | None, datetime | None, int]:
    now = datetime.now(timezone.utc)
    if period == "today":
        start = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
        return start, now, 1
    if period == "30d":
        return now - timedelta(days=30), now, 30
    if period == "all":
        return None, now, 90
    if period == "custom":
        start = _parse_date(date_from)
        end = _parse_date(date_to, end_of_day=True) or now
        days = max((end.date() - start.date()).days + 1, 1) if start else 30
        return start, end, min(days, 180)
    if period.endswith("d") and period[:-1].isdigit():
        days = max(min(int(period[:-1]), 180), 1)
        return now - timedelta(days=days), now, days
    return now - timedelta(days=7), now, 7


def _apply_range(query, column, start: datetime | None, end: datetime | None):
    if start:
        query = query.filter(column >= start)
    if end:
        query = query.filter(column <= end)
    return query


def _count(query) -> int:
    return int(query.count() or 0)


def _delta_total(db: Session, model, column, current_start: datetime | None, current_end: datetime | None) -> dict[str, Any]:
    current = _count(_apply_range(db.query(model), column, current_start, current_end))
    if not current_start or not current_end:
        return {"total": current, "delta": 0, "delta_percent": 0}
    span = current_end - current_start
    previous_start = current_start - span
    previous_end = current_start
    previous = _count(_apply_range(db.query(model), column, previous_start, previous_end))
    delta = current - previous
    return {
        "total": current,
        "delta": delta,
        "delta_percent": round(delta / previous * 100, 2) if previous else (100 if current else 0),
    }


def _active_user_query(db: Session):
    return db.query(TelegramUser).filter(
        TelegramUser.is_blocked.is_(False),
        TelegramUser.unsubscribed.is_(False),
    )


def _event_count(db: Session, event_types: list[str], start: datetime | None, end: datetime | None) -> int:
    lead_event_query = db.query(LeadEvent).filter(LeadEvent.type.in_(event_types))
    event_log_query = db.query(EventLog).filter(EventLog.event_type.in_(event_types))
    return _count(_apply_range(lead_event_query, LeadEvent.created_at, start, end)) + _count(
        _apply_range(event_log_query, EventLog.created_at, start, end)
    )


def _funnel_payload(db: Session, start: datetime | None, end: datetime | None) -> dict:
    steps = [
        ("start", "Start", ["start", "user_started_bot"]),
        ("consent", "Consent", ["consent_accepted"]),
        ("name", "Name", ["answered_name", "name_submitted"]),
        ("photo", "Photo", ["photo_uploaded"]),
        ("selected_problems", "Selected problems", ["problems_selected"]),
        ("protocol_generated", "Protocol generated", ["protocol_generated", "protocol_sent", "scenario_completed"]),
        ("report_opened", "Report opened", ["report_opened"]),
        ("cta_clicked", "CTA clicked", ["cta_clicked"]),
    ]
    items = []
    previous_count: int | None = None
    first_count: int | None = None
    for key, label, event_types in steps:
        if key == "protocol_generated":
            count = _count(_apply_range(db.query(AnalysisRequest).filter(AnalysisRequest.status == AnalysisStatus.COMPLETED), AnalysisRequest.completed_at, start, end))
        elif key == "report_opened":
            count = _count(_apply_range(db.query(ReportViewEvent), ReportViewEvent.created_at, start, end))
        elif key == "cta_clicked":
            count = _count(_apply_range(db.query(CtaClickEvent), CtaClickEvent.created_at, start, end))
        else:
            count = _event_count(db, event_types, start, end)
        if first_count is None:
            first_count = count
        items.append(
            {
                "key": key,
                "label": label,
                "count": count,
                "from_start_percent": round(count / first_count * 100, 2) if first_count else 0,
                "from_previous_percent": round(count / previous_count * 100, 2) if previous_count else 0,
            }
        )
        previous_count = count
    return {"items": items}


def _users_by_day(db: Session, start: datetime | None, end: datetime | None):
    query = db.query(func.date(TelegramUser.created_at).label("date"), func.count(TelegramUser.id).label("count"))
    query = _apply_range(query, TelegramUser.created_at, start, end)
    return [{"date": str(day), "count": count} for day, count in query.group_by("date").order_by("date").all()]


def _analyses_by_day(db: Session, start: datetime | None, end: datetime | None):
    query = db.query(func.date(AnalysisRequest.created_at).label("date"), func.count(AnalysisRequest.id).label("count"))
    query = _apply_range(query, AnalysisRequest.created_at, start, end)
    return [{"date": str(day), "count": count} for day, count in query.group_by("date").order_by("date").all()]


def _top_problems(db: Session, start: datetime | None, end: datetime | None):
    query = db.query(SelectedProblem.title, func.count(SelectedProblem.id).label("count"))
    query = _apply_range(query, SelectedProblem.created_at, start, end)
    return [
        {"title": title or "unknown", "count": count}
        for title, count in query.group_by(SelectedProblem.title).order_by(func.count(SelectedProblem.id).desc()).limit(8).all()
    ]


def _top_sources(db: Session, start: datetime | None, end: datetime | None):
    query = db.query(Lead.source, func.count(Lead.id).label("count")).filter(Lead.source.is_not(None))
    query = _apply_range(query, Lead.created_at, start, end)
    return [
        {"source": source or "unknown", "count": count}
        for source, count in query.group_by(Lead.source).order_by(func.count(Lead.id).desc()).limit(8).all()
    ]


def _latest_leads(db: Session):
    leads = (
        db.query(Lead)
        .options(selectinload(Lead.telegram_user), selectinload(Lead.assigned_manager))
        .order_by(func.coalesce(Lead.last_activity_at, Lead.updated_at, Lead.created_at).desc())
        .limit(10)
        .all()
    )
    return [
        {
            "id": lead.id,
            "name": lead.name,
            "status": lead.crm_status,
            "technical_status": lead.status,
            "selected_problems": lead.selected_problems or [],
            "source": lead.source,
            "report_opened": lead.report_opened,
            "cta_clicked": lead.cta_clicked,
            "created_at": lead.created_at,
            "last_activity_at": lead.last_activity_at or lead.updated_at,
            "telegram_user": {
                "telegram_id": lead.telegram_user.telegram_id,
                "username": lead.telegram_user.username,
            }
            if lead.telegram_user
            else None,
            "assigned_manager": {"id": lead.assigned_manager.id, "name": lead.assigned_manager.name, "email": lead.assigned_manager.email}
            if lead.assigned_manager
            else None,
        }
        for lead in leads
    ]


@admin_router.get("/stats")
def admin_stats(
    _: AdminAuth,
    db: Session = Depends(get_db),
    period: str = Query("7d"),
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    start, end, _ = _period_range(period, date_from, date_to)
    total_users = _count(db.query(TelegramUser))
    blocked_or_unsubscribed = _count(db.query(TelegramUser).filter(or_(TelegramUser.is_blocked.is_(True), TelegramUser.unsubscribed.is_(True))))
    active_users = _count(_active_user_query(db))
    total_memberships = _count(db.query(AudienceBaseMember))
    unique_users_in_bases = db.query(func.count(func.distinct(AudienceBaseMember.telegram_user_id))).scalar() or 0
    active_leads = _count(db.query(Lead).filter(~Lead.crm_status.in_(TERMINAL_CRM_STATUSES)))
    completed_analyses = _count(db.query(AnalysisRequest).filter(AnalysisRequest.status == AnalysisStatus.COMPLETED))
    failed_jobs = _count(db.query(AiJobLog).filter(AiJobLog.status == "failed")) + _count(
        db.query(AnalysisRequest).filter(AnalysisRequest.status.in_([AnalysisStatus.FAILED, AnalysisStatus.FAILED_PROTOCOL_RENDER]))
    )
    needs_review = _count(db.query(AnalysisRequest).filter(AnalysisRequest.status == AnalysisStatus.NEEDS_REVIEW))
    period_users = _delta_total(db, TelegramUser, TelegramUser.created_at, start, end)
    today_start = datetime.combine(datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc)
    return {
        "period": {"key": period, "date_from": start, "date_to": end},
        "cards": {
            "active_users": active_users,
            "blocked_or_unsubscribed": blocked_or_unsubscribed,
            "blocked_percent": round(blocked_or_unsubscribed / total_users * 100, 2) if total_users else 0,
            "total_users": total_users,
            "period_new_users": period_users,
            "new_users_today": _count(db.query(TelegramUser).filter(TelegramUser.created_at >= today_start)),
            "new_users_7d": _count(db.query(TelegramUser).filter(TelegramUser.created_at >= datetime.now(timezone.utc) - timedelta(days=7))),
            "new_users_30d": _count(db.query(TelegramUser).filter(TelegramUser.created_at >= datetime.now(timezone.utc) - timedelta(days=30))),
            "bases_count": _count(db.query(AudienceBase)),
            "total_memberships": total_memberships,
            "unique_users_in_bases": int(unique_users_in_bases),
            "completed_analyses": completed_analyses,
            "active_leads": active_leads,
            "ai_errors": failed_jobs,
            "needs_manual_review": needs_review,
        },
        "latest_leads": _latest_leads(db),
    }


@admin_router.get("/funnel")
def admin_funnel(
    _: AdminAuth,
    db: Session = Depends(get_db),
    period: str = Query("7d"),
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    start, end, _ = _period_range(period, date_from, date_to)
    payload = _funnel_payload(db, start, end)
    payload["period"] = {"key": period, "date_from": start, "date_to": end}
    return payload


@admin_router.get("/charts")
def admin_charts(
    _: AdminAuth,
    db: Session = Depends(get_db),
    period: str = Query("7d"),
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict:
    start, end, _ = _period_range(period, date_from, date_to)
    return {
        "period": {"key": period, "date_from": start, "date_to": end},
        "users_by_day": _users_by_day(db, start, end),
        "analyses_by_day": _analyses_by_day(db, start, end),
        "top_problems": _top_problems(db, start, end),
        "top_sources": _top_sources(db, start, end),
    }


@router.get("/stats")
def legacy_stats(admin: AdminAuth, db: Session = Depends(get_db)) -> dict:
    stats_payload = admin_stats(admin, db, period="14d")
    charts = admin_charts(admin, db, period="14d")
    funnel = admin_funnel(admin, db, period="14d")
    cards = stats_payload["cards"]
    funnel_items = {item["key"]: item["count"] for item in funnel["items"]}
    reports = _count(db.query(GeneratedReport))
    opened = funnel_items.get("report_opened", 0)
    cta = funnel_items.get("cta_clicked", 0)
    photo_count = funnel_items.get("photo", 0)
    completed = cards["completed_analyses"]
    users = cards["total_users"]
    return {
        "cards": {
            "users": users,
            "new_leads": _count(db.query(Lead)),
            "completed_analyses": completed,
            "ai_errors": cards["ai_errors"],
        },
        "conversion": {
            "start": funnel_items.get("start", users),
            "photo": photo_count,
            "analysis": completed,
            "report_opened": opened,
            "cta_clicked": cta,
            "start_to_photo": round(photo_count / users * 100, 2) if users else 0,
            "photo_to_analysis": round(completed / photo_count * 100, 2) if photo_count else 0,
            "analysis_to_report_opened": round(opened / reports * 100, 2) if reports else 0,
            "report_to_cta": round(cta / opened * 100, 2) if opened else 0,
        },
        "requests_by_day": charts["analyses_by_day"],
        "top_problems": charts["top_problems"],
        "sources": charts["top_sources"],
        "latest_leads": stats_payload["latest_leads"],
    }
