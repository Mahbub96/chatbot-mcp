from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class MemoryRecord(Base):
    __tablename__ = "memory_records"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), index=True, default="global")
    memory_scope: Mapped[str] = mapped_column(String(128), index=True, default="global")
    text: Mapped[str] = mapped_column(Text())
    source: Mapped[str] = mapped_column(String(64), default="chat")
    importance: Mapped[float] = mapped_column(Float(), default=0.5)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=datetime.utcnow, index=True)

