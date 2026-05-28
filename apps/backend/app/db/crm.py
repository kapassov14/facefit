from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import CampaignSource, Lead, LeadActivity, LeadEvent, LeadTag, Tag, Touchpoint


def touch_lead(lead: Lead) -> None:
    lead.last_activity_at = datetime.now(timezone.utc)


def add_lead_event(
    db: Session,
    lead: Lead | None,
    event_type: str,
    title: str,
    metadata: dict[str, Any] | None = None,
    admin_id: int | None = None,
) -> None:
    if not lead or not lead.id:
        return
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
    touch_lead(lead)


def get_or_create_tag(db: Session, name: str, color: str | None = None) -> Tag | None:
    cleaned = " ".join(name.strip().split())[:120]
    if not cleaned:
        return None
    tag = db.query(Tag).filter(func.lower(Tag.name) == cleaned.lower()).first()
    if tag:
        return tag
    tag = Tag(name=cleaned, color=color or "#f2e7de")
    db.add(tag)
    db.flush()
    return tag


def add_tags_to_lead(db: Session, lead: Lead, tags: list[str]) -> None:
    current = [item for item in (lead.tags or []) if item]
    for item in tags:
        tag = get_or_create_tag(db, item)
        if not tag:
            continue
        if tag.name not in current:
            current.append(tag.name)
        if not any(link.tag_id == tag.id for link in lead.tag_links):
            lead.tag_links.append(LeadTag(tag=tag))
    lead.tags = current


def apply_source_link_to_lead(db: Session, lead: Lead, source_link: CampaignSource, payload: str | None) -> None:
    if not lead.id:
        db.flush()
    if not lead.first_source_link_id:
        lead.first_source_link_id = source_link.id
    lead.last_source_link_id = source_link.id
    lead.source = source_link.source or payload or lead.source
    if source_link.audience_id:
        lead.audience_id = source_link.audience_id
    if source_link.assigned_manager_id:
        lead.assigned_manager_id = source_link.assigned_manager_id
    add_tags_to_lead(db, lead, source_link.auto_tags or [])
    touch_lead(lead)
    db.add(
        Touchpoint(
            lead_id=lead.id,
            source_link_id=source_link.id,
            source=source_link.source,
            campaign=source_link.campaign,
            payload={"start_payload": payload, "slug": source_link.slug, "name": source_link.title},
        )
    )
    add_lead_event(
        db,
        lead,
        "source_link_visit",
        f"Пользователь перешел по ссылке {source_link.title}",
        {"source": source_link.source, "campaign": source_link.campaign, "slug": source_link.slug},
    )
