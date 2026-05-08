from __future__ import annotations

from datetime import datetime, UTC

from sqlalchemy import DateTime, Float, Index, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class MemoryRecord(Base):
    __tablename__ = "memory_records"
    __table_args__ = (
        Index("ix_memory_scope_created_at", "memory_scope", "created_at"),
        Index("ix_memory_scope_source_created_at", "memory_scope", "source", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True, default="global")
    memory_scope: Mapped[str] = mapped_column(String(128), index=True, default="global")
    text: Mapped[str] = mapped_column(Text())
    source: Mapped[str] = mapped_column(String(64), default="chat")
    category: Mapped[str] = mapped_column(String(64), default="general")
    structured_data: Mapped[str] = mapped_column(Text(), default="{}")
    importance: Mapped[float] = mapped_column(Float(), default=0.5)
    confidence: Mapped[float] = mapped_column(Float(), default=0.5)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=lambda: datetime.now(UTC), index=True)


class ChatTraceRecord(Base):
    __tablename__ = "chat_trace_records"
    __table_args__ = (
        Index("ix_chat_trace_scope_created_at", "memory_scope", "created_at"),
        Index("ix_chat_trace_request_id", "request_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True, default="global")
    memory_scope: Mapped[str] = mapped_column(String(128), index=True, default="global")
    user_text: Mapped[str] = mapped_column(Text())
    assistant_text: Mapped[str] = mapped_column(Text())
    model: Mapped[str] = mapped_column(String(128), default="")
    confidence: Mapped[float] = mapped_column(Float(), default=0.5)
    retrieval_summary: Mapped[str] = mapped_column(Text(), default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=lambda: datetime.now(UTC), index=True)
