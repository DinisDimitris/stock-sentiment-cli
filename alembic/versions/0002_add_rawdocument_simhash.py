"""Add simhash to raw_documents

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-08
"""

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("raw_documents", sa.Column("simhash", sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column("raw_documents", "simhash")
