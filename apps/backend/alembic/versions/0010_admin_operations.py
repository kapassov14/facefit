"""add admin operations crm bases broadcasts

Revision ID: 0010_admin_operations
Revises: 0009_lead_age
Create Date: 2026-05-28
"""

from alembic import op
import sqlalchemy as sa


revision = "0010_admin_operations"
down_revision = "0009_lead_age"
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
    if table_name in _tables() and name not in _indexes(table_name):
        op.create_index(name, table_name, columns, unique=unique)


def _add_column(table_name: str, column: sa.Column) -> None:
    if table_name in _tables() and column.name not in _columns(table_name):
        op.add_column(table_name, column)


def upgrade() -> None:
    _add_column("admin_users", sa.Column("name", sa.String(length=255), nullable=True))
    _add_column("admin_users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    _add_column("admin_users", sa.Column("can_broadcast", sa.Boolean(), nullable=False, server_default=sa.false()))

    _add_column("telegram_users", sa.Column("is_blocked", sa.Boolean(), nullable=False, server_default=sa.false()))
    _add_column("telegram_users", sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=True))
    _add_column("telegram_users", sa.Column("unsubscribed", sa.Boolean(), nullable=False, server_default=sa.false()))
    _add_column("telegram_users", sa.Column("unsubscribed_at", sa.DateTime(timezone=True), nullable=True))
    _add_column("telegram_users", sa.Column("last_bot_interaction_at", sa.DateTime(timezone=True), nullable=True))
    _add_column("telegram_users", sa.Column("last_message_sent_at", sa.DateTime(timezone=True), nullable=True))
    _add_column("telegram_users", sa.Column("last_message_error", sa.Text(), nullable=True))
    _create_index("ix_telegram_users_is_blocked", "telegram_users", ["is_blocked"])
    _create_index("ix_telegram_users_unsubscribed", "telegram_users", ["unsubscribed"])

    _add_column("leads", sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True))
    _add_column("leads", sa.Column("assigned_by_id", sa.Integer(), sa.ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True))
    _create_index("ix_leads_assigned_manager_id", "leads", ["assigned_manager_id"])
    _create_index("ix_leads_created_at", "leads", ["created_at"])

    if "lead_activities" not in _tables():
        op.create_table(
            "lead_activities",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False),
            sa.Column("actor_type", sa.String(length=32), nullable=False, server_default="system"),
            sa.Column("actor_id", sa.Integer(), sa.ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("event_type", sa.String(length=120), nullable=False),
            sa.Column("payload_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        )
    _create_index("ix_lead_activities_lead_id", "lead_activities", ["lead_id"])
    _create_index("ix_lead_activities_actor_type", "lead_activities", ["actor_type"])
    _create_index("ix_lead_activities_event_type", "lead_activities", ["event_type"])

    if "lead_tasks" not in _tables():
        op.create_table(
            "lead_tasks",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False),
            sa.Column("assigned_to_id", sa.Integer(), sa.ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="todo"),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        )
    _create_index("ix_lead_tasks_lead_id", "lead_tasks", ["lead_id"])
    _create_index("ix_lead_tasks_assigned_to_id", "lead_tasks", ["assigned_to_id"])
    _create_index("ix_lead_tasks_due_at", "lead_tasks", ["due_at"])
    _create_index("ix_lead_tasks_status", "lead_tasks", ["status"])

    if "audience_bases" not in _tables():
        op.create_table(
            "audience_bases",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("type", sa.String(length=32), nullable=False, server_default="static"),
            sa.Column("filters_json", sa.JSON(), nullable=True),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
        )
    _create_index("ix_audience_bases_name", "audience_bases", ["name"], unique=True)
    _create_index("ix_audience_bases_type", "audience_bases", ["type"])

    if "audience_base_members" not in _tables():
        op.create_table(
            "audience_base_members",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("base_id", sa.Integer(), sa.ForeignKey("audience_bases.id", ondelete="CASCADE"), nullable=False),
            sa.Column("lead_id", sa.Integer(), sa.ForeignKey("leads.id", ondelete="CASCADE"), nullable=False),
            sa.Column("telegram_user_id", sa.Integer(), sa.ForeignKey("telegram_users.id", ondelete="CASCADE"), nullable=True),
            sa.Column("added_by_id", sa.Integer(), sa.ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True),
            sa.Column("added_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
            sa.UniqueConstraint("base_id", "lead_id", name="uq_audience_base_members_base_lead"),
        )
    _create_index("ix_audience_base_members_base_id", "audience_base_members", ["base_id"])
    _create_index("ix_audience_base_members_lead_id", "audience_base_members", ["lead_id"])
    _create_index("ix_audience_base_members_telegram_user_id", "audience_base_members", ["telegram_user_id"])
    _create_index("ix_audience_base_members_added_at", "audience_base_members", ["added_at"])

    _add_column("broadcasts", sa.Column("base_id", sa.Integer(), sa.ForeignKey("audience_bases.id", ondelete="SET NULL"), nullable=True))
    _add_column("broadcasts", sa.Column("media_type", sa.String(length=64), nullable=True))
    _add_column("broadcasts", sa.Column("message_text", sa.Text(), nullable=True))
    _add_column("broadcasts", sa.Column("media_url", sa.String(length=1000), nullable=True))
    _add_column("broadcasts", sa.Column("buttons_json", sa.JSON(), nullable=True))
    _add_column("broadcasts", sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True))
    _add_column("broadcasts", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    _add_column("broadcasts", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    _add_column("broadcasts", sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True))
    _add_column("broadcasts", sa.Column("rate_limit_per_second", sa.Integer(), nullable=False, server_default="10"))
    _create_index("ix_broadcasts_base_id", "broadcasts", ["base_id"])
    _create_index("ix_broadcasts_status", "broadcasts", ["status"])

    _add_column("broadcast_recipients", sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True))
    _add_column("broadcast_recipients", sa.Column("telegram_message_id", sa.Integer(), nullable=True))
    _create_index("ix_broadcast_recipients_broadcast_id", "broadcast_recipients", ["broadcast_id"])
    _create_index("ix_broadcast_recipients_status", "broadcast_recipients", ["status"])


def downgrade() -> None:
    for table_name, columns in {
        "broadcast_recipients": ["telegram_message_id", "sent_at"],
        "broadcasts": [
            "rate_limit_per_second",
            "created_by_id",
            "completed_at",
            "started_at",
            "scheduled_at",
            "buttons_json",
            "media_url",
            "message_text",
            "media_type",
            "base_id",
        ],
        "leads": ["assigned_by_id", "assigned_at"],
        "telegram_users": [
            "last_message_error",
            "last_message_sent_at",
            "last_bot_interaction_at",
            "unsubscribed_at",
            "unsubscribed",
            "blocked_at",
            "is_blocked",
        ],
        "admin_users": ["can_broadcast", "last_login_at", "name"],
    }.items():
        existing = _columns(table_name)
        for column in columns:
            if column in existing:
                op.drop_column(table_name, column)
    for table in ["audience_base_members", "audience_bases", "lead_tasks", "lead_activities"]:
        if table in _tables():
            op.drop_table(table)
