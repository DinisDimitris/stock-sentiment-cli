"""Initial schema

Revision ID: 0001
Revises:
Create Date: 2026-08-01
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("sector", sa.Text(), nullable=True),
        sa.Column("industry", sa.Text(), nullable=True),
        sa.Column("backfill_status", sa.String(), server_default="pending"),
        sa.Column("backfill_completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("added_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("ticker"),
    )

    op.create_table(
        "ticker_aliases",
        sa.Column("alias", sa.Text(), nullable=False),
        sa.Column("ticker", sa.String(), sa.ForeignKey("companies.ticker"), nullable=False),
        sa.Column("alias_type", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), server_default="1.0"),
        sa.PrimaryKeyConstraint("alias", "ticker"),
    )

    op.create_table(
        "source_tiers",
        sa.Column("source_name", sa.Text(), nullable=False),
        sa.Column("tier", sa.Integer(), nullable=False),
        sa.Column("base_weight", sa.Float(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("source_name"),
    )

    op.create_table(
        "raw_documents",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_subtype", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True, unique=True),
        sa.Column("content_hash", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("published_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("retrieved_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column("raw_json", postgresql.JSONB(), nullable=True),
        sa.Column("fast_lane", sa.Boolean(), server_default="false"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_docs_content_hash", "raw_documents", ["content_hash"])
    op.create_index("idx_docs_published_at", "raw_documents", ["published_at"])

    op.create_table(
        "document_companies",
        sa.Column("document_id", sa.BigInteger(), sa.ForeignKey("raw_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ticker", sa.String(), sa.ForeignKey("companies.ticker"), nullable=False),
        sa.Column("confidence", sa.Float(), server_default="1.0"),
        sa.PrimaryKeyConstraint("document_id", "ticker"),
    )
    op.create_index("idx_doc_companies_ticker", "document_companies", ["ticker"])

    op.create_table(
        "events",
        sa.Column("event_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("importance", sa.String(), server_default="MEDIUM"),
        sa.Column("simhash", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("event_id"),
    )

    op.create_table(
        "event_documents",
        sa.Column("event_id", sa.BigInteger(), sa.ForeignKey("events.event_id"), nullable=False),
        sa.Column("document_id", sa.BigInteger(), sa.ForeignKey("raw_documents.id"), nullable=False),
        sa.PrimaryKeyConstraint("event_id", "document_id"),
    )

    op.create_table(
        "task_queue",
        sa.Column("task_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("task_type", sa.Text(), nullable=False),
        sa.Column("priority", sa.String(), server_default="STANDARD"),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(), server_default="pending"),
        sa.Column("attempts", sa.Integer(), server_default="0"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column("claimed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("task_id"),
    )

    op.create_table(
        "analysis_runs",
        sa.Column("run_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ticker", sa.String(), nullable=False),
        sa.Column("requested_at", sa.TIMESTAMP(timezone=True), server_default=sa.func.now()),
        sa.Column("composite_score_1d", sa.Float(), nullable=True),
        sa.Column("composite_score_7d", sa.Float(), nullable=True),
        sa.Column("composite_score_30d", sa.Float(), nullable=True),
        sa.Column("direction", sa.Text(), nullable=True),
        sa.Column("confidence_pct", sa.Integer(), nullable=True),
        sa.Column("agent_summary", sa.Text(), nullable=True),
        sa.Column("raw_agent_response", postgresql.JSONB(), nullable=True),
        sa.Column("expires_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("run_id"),
    )
    op.create_index("idx_analysis_ticker_expires", "analysis_runs", ["ticker", "expires_at"])


def downgrade() -> None:
    op.drop_table("analysis_runs")
    op.drop_table("task_queue")
    op.drop_table("event_documents")
    op.drop_table("events")
    op.drop_table("document_companies")
    op.drop_table("raw_documents")
    op.drop_table("source_tiers")
    op.drop_table("ticker_aliases")
    op.drop_table("companies")
