"""add crm audiences source links

Revision ID: 0008_crm_source_links
Revises: 0007_personal_insight_json
Create Date: 2026-05-20
"""

from alembic import op
import sqlalchemy as sa


revision = "0008_crm_source_links"
down_revision = "0007_personal_insight_json"
branch_labels = None
depends_on = None


def _tables() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def _columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table_name not in set(inspector.get_table_names()):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def _indexes(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table_name not in set(inspector.get_table_names()):
        return set()
    return {index["name"] for index in inspector.get_indexes(table_name)}


def _create_index(name: str, table_name: str, columns: list[str], unique: bool = False) -> None:
    if name not in _indexes(table_name):
        op.create_index(name, table_name, columns, unique=unique)


def upgrade() -> None:
    existing_tables = _tables()
    if "audiences" not in existing_tables:
        op.create_table(
            "audiences",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("color", sa.String(length=32), nullable=False, server_default="#be7d86"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        )
        _create_index("ix_audiences_name", "audiences", ["name"], unique=True)

    if "tags" not in existing_tables:
        op.create_table(
            "tags",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=120), nullable=False),
            sa.Column("color", sa.String(length=32), nullable=False, server_default="#f2e7de"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        )
        _create_index("ix_tags_name", "tags", ["name"], unique=True)

    campaign_columns = _columns("campaign_sources")
    campaign_additions = {
        "source": sa.Column("source", sa.String(length=80), nullable=True),
        "campaign": sa.Column("campaign", sa.String(length=255), nullable=True),
        "description": sa.Column("description", sa.Text(), nullable=True),
        "audience_id": sa.Column("audience_id", sa.Integer(), sa.ForeignKey("audiences.id", ondelete="SET NULL"), nullable=True),
        "funnel_id": sa.Column("funnel_id", sa.Integer(), nullable=True),
        "assigned_manager_id": sa.Column("assigned_manager_id", sa.Integer(), sa.ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True),
        "auto_tags": sa.Column("auto_tags", sa.JSON(), nullable=True),
    }
    for name, column in campaign_additions.items():
        if name not in campaign_columns:
            op.add_column("campaign_sources", column)
    if "campaign_sources" in _tables():
        _create_index("ix_campaign_sources_source", "campaign_sources", ["source"])
        _create_index("ix_campaign_sources_campaign", "campaign_sources", ["campaign"])

    lead_columns = _columns("leads")
    lead_additions = {
        "phone": sa.Column("phone", sa.String(length=64), nullable=True),
        "crm_status": sa.Column("crm_status", sa.String(length=64), nullable=False, server_default="new"),
        "first_source_link_id": sa.Column("first_source_link_id", sa.Integer(), sa.ForeignKey("campaign_sources.id", ondelete="SET NULL"), nullable=True),
        "last_source_link_id": sa.Column("last_source_link_id", sa.Integer(), sa.ForeignKey("campaign_sources.id", ondelete="SET NULL"), nullable=True),
        "audience_id": sa.Column("audience_id", sa.Integer(), sa.ForeignKey("audiences.id", ondelete="SET NULL"), nullable=True),
        "assigned_manager_id": sa.Column("assigned_manager_id", sa.Integer(), sa.ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True),
        "last_activity_at": sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
    }
    for name, column in lead_additions.items():
        if name not in lead_columns:
            op.add_column("leads", column)
    if "leads" in _tables():
        _create_index("ix_leads_phone", "leads", ["phone"])
        _create_index("ix_leads_crm_status", "leads", ["crm_status"])
        _create_index("ix_leads_last_activity_at", "leads", ["last_activity_at"])

    if "lead_tags" not in _tables():
        op.create_table(
            "lead_tags",
            sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("tag_id", sa.Integer(), sa.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.UniqueConstraint("lead_id", "tag_id", name="uq_lead_tags_lead_tag"),
        )

    if "lead_events" not in _tables():
        op.create_table(
            "lead_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False),
            sa.Column("type", sa.String(length=120), nullable=False),
            sa.Column("title", sa.String(length=500), nullable=False),
            sa.Column("metadata", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True),
        )
        _create_index("ix_lead_events_lead_id", "lead_events", ["lead_id"])
        _create_index("ix_lead_events_type", "lead_events", ["type"])
        _create_index("ix_lead_events_created_at", "lead_events", ["created_at"])

    if "touchpoints" not in _tables():
        op.create_table(
            "touchpoints",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False),
            sa.Column("source_link_id", sa.Integer(), sa.ForeignKey("campaign_sources.id", ondelete="SET NULL"), nullable=True),
            sa.Column("source", sa.String(length=80), nullable=True),
            sa.Column("campaign", sa.String(length=255), nullable=True),
            sa.Column("payload", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        )
        _create_index("ix_touchpoints_lead_id", "touchpoints", ["lead_id"])
        _create_index("ix_touchpoints_source_link_id", "touchpoints", ["source_link_id"])
        _create_index("ix_touchpoints_source", "touchpoints", ["source"])
        _create_index("ix_touchpoints_campaign", "touchpoints", ["campaign"])
        _create_index("ix_touchpoints_created_at", "touchpoints", ["created_at"])


def downgrade() -> None:
    for table in ["touchpoints", "lead_events", "lead_tags"]:
        if table in _tables():
            op.drop_table(table)

    for table_name, columns in {
        "leads": [
            "last_activity_at",
            "assigned_manager_id",
            "audience_id",
            "last_source_link_id",
            "first_source_link_id",
            "crm_status",
            "phone",
        ],
        "campaign_sources": [
            "auto_tags",
            "assigned_manager_id",
            "funnel_id",
            "audience_id",
            "description",
            "campaign",
            "source",
        ],
    }.items():
        existing = _columns(table_name)
        for column in columns:
            if column in existing:
                op.drop_column(table_name, column)

    for table in ["tags", "audiences"]:
        if table in _tables():
            op.drop_table(table)
