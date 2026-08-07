from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, Column, Float, ForeignKey,
    Index, Integer, String, Text, UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Company(Base):
    __tablename__ = "companies"

    ticker = Column(String, primary_key=True)
    name = Column(Text, nullable=False)
    sector = Column(Text)
    industry = Column(Text)
    backfill_status = Column(String, default="pending")
    backfill_completed_at = Column(TIMESTAMP(timezone=True))
    added_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    aliases = relationship("TickerAlias", back_populates="company")
    document_companies = relationship("DocumentCompany", back_populates="company")


class TickerAlias(Base):
    __tablename__ = "ticker_aliases"

    alias = Column(Text, nullable=False, primary_key=True)
    ticker = Column(String, ForeignKey("companies.ticker"), primary_key=True)
    alias_type = Column(Text, nullable=False)  # common_name|user_resolved|sec_edgar|finnhub
    confidence = Column(Float, default=1.0)

    company = relationship("Company", back_populates="aliases")


class SourceTier(Base):
    __tablename__ = "source_tiers"

    source_name = Column(Text, primary_key=True)
    tier = Column(Integer, nullable=False)
    base_weight = Column(Float, nullable=False)
    description = Column(Text)


class RawDocument(Base):
    __tablename__ = "raw_documents"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    source = Column(Text, nullable=False)
    source_subtype = Column(Text)
    url = Column(Text, unique=True)
    content_hash = Column(Text)
    title = Column(Text)
    body = Column(Text)
    published_at = Column(TIMESTAMP(timezone=True))
    retrieved_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    raw_json = Column(JSONB)
    fast_lane = Column(Boolean, default=False)

    document_companies = relationship("DocumentCompany", back_populates="document")
    event_documents = relationship("EventDocument", back_populates="document")

    __table_args__ = (
        Index("idx_docs_content_hash", "content_hash"),
        Index("idx_docs_published_at", "published_at"),
        Index("idx_docs_source", "source", "published_at"),
    )


class DocumentCompany(Base):
    __tablename__ = "document_companies"

    document_id = Column(BigInteger, ForeignKey("raw_documents.id", ondelete="CASCADE"), primary_key=True)
    ticker = Column(String, ForeignKey("companies.ticker"), primary_key=True)
    confidence = Column(Float, default=1.0)

    document = relationship("RawDocument", back_populates="document_companies")
    company = relationship("Company", back_populates="document_companies")

    __table_args__ = (
        Index("idx_doc_companies_ticker", "ticker"),
    )


class Event(Base):
    __tablename__ = "events"

    event_id = Column(BigInteger, primary_key=True, autoincrement=True)
    event_type = Column(Text, nullable=False)
    headline = Column(Text, nullable=False)
    summary = Column(Text)
    importance = Column(String, default="MEDIUM")
    simhash = Column(BigInteger)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

    event_documents = relationship("EventDocument", back_populates="event")


class EventDocument(Base):
    __tablename__ = "event_documents"

    event_id = Column(BigInteger, ForeignKey("events.event_id"), primary_key=True)
    document_id = Column(BigInteger, ForeignKey("raw_documents.id"), primary_key=True)

    event = relationship("Event", back_populates="event_documents")
    document = relationship("RawDocument", back_populates="event_documents")


class TaskQueue(Base):
    __tablename__ = "task_queue"

    task_id = Column(BigInteger, primary_key=True, autoincrement=True)
    task_type = Column(Text, nullable=False)
    priority = Column(String, nullable=False, default="STANDARD")
    payload = Column(JSONB, nullable=False)
    status = Column(String, nullable=False, default="pending")
    attempts = Column(Integer, default=0)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    claimed_at = Column(TIMESTAMP(timezone=True))
    completed_at = Column(TIMESTAMP(timezone=True))

    __table_args__ = (
        Index("idx_task_queue_pending", "priority", "created_at",
              postgresql_where="status = 'pending'"),
    )


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    run_id = Column(BigInteger, primary_key=True, autoincrement=True)
    ticker = Column(String, nullable=False)
    requested_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
    composite_score_1d = Column(Float)
    composite_score_7d = Column(Float)
    composite_score_30d = Column(Float)
    direction = Column(Text)
    confidence_pct = Column(Integer)
    agent_summary = Column(Text)
    raw_agent_response = Column(JSONB)
    expires_at = Column(TIMESTAMP(timezone=True))

    __table_args__ = (
        Index("idx_analysis_ticker_expires", "ticker", "expires_at"),
    )
