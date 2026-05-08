from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy import text as sql_text
from sqlalchemy.orm import sessionmaker

from config import MEMORY_SQLITE_URL
from memory.models import Base


def create_engine_and_session():
    if MEMORY_SQLITE_URL.startswith("sqlite:///"):
        db_path = MEMORY_SQLITE_URL.replace("sqlite:///", "", 1)
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

    engine = create_engine(MEMORY_SQLITE_URL, future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(engine)
    _ensure_memory_scope_column(engine)
    return engine, SessionLocal


def _ensure_memory_scope_column(engine) -> None:
    if not MEMORY_SQLITE_URL.startswith("sqlite:///"):
        return
    with engine.begin() as conn:
        rows = conn.execute(sql_text("PRAGMA table_info(memory_records)")).fetchall()
        if not rows:
            return
        cols = {r[1] for r in rows}
        if "memory_scope" in cols:
            return
        conn.execute(
            sql_text(
                "ALTER TABLE memory_records "
                "ADD COLUMN memory_scope VARCHAR(128) NOT NULL DEFAULT 'global'"
            )
        )

