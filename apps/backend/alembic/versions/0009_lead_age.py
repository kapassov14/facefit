"""add lead age

Revision ID: 0009_lead_age
Revises: 0008_crm_source_links
Create Date: 2026-05-24
"""

from alembic import op
import sqlalchemy as sa


revision = "0009_lead_age"
down_revision = "0008_crm_source_links"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table_name not in set(inspector.get_table_names()):
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def upgrade() -> None:
    if "age" not in _columns("leads"):
        op.add_column("leads", sa.Column("age", sa.Integer(), nullable=True))


def downgrade() -> None:
    if "age" in _columns("leads"):
        op.drop_column("leads", "age")
