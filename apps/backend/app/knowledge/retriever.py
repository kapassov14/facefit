from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import KnowledgeChunk, KnowledgeDocument


def retrieve_context(db: Session, selected_problems: list[str], limit: int = 20) -> str:
    chunks = (
        db.query(KnowledgeChunk)
        .join(KnowledgeDocument)
        .filter(KnowledgeChunk.is_active.is_(True), KnowledgeDocument.is_active.is_(True))
        .order_by(KnowledgeChunk.id.asc())
        .limit(limit)
        .all()
    )
    return "\n\n".join(chunk.content for chunk in chunks)
