from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy import text as sql_text
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from config import MEMORY_SQLITE_URL
from memory.models import Base

SQLITE_URL_PREFIX = "sqlite:///"
MEMORY_RECORDS_TABLE_INFO_SQL = "PRAGMA table_info(memory_records)"


def create_engine_and_session():
    if MEMORY_SQLITE_URL.startswith(SQLITE_URL_PREFIX):
        db_path = MEMORY_SQLITE_URL.replace(SQLITE_URL_PREFIX, "", 1)
        db_dir = os.path.dirname(db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

    engine = create_engine(MEMORY_SQLITE_URL, future=True)
    if MEMORY_SQLITE_URL.startswith(SQLITE_URL_PREFIX):
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA temp_store=MEMORY")
            cursor.execute("PRAGMA cache_size=-20000")
            cursor.close()
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    try:
        Base.metadata.create_all(engine)
    except OperationalError as exc:
        # Rare SQLite race: another process creates table after SQLAlchemy checkfirst.
        if "already exists" not in str(exc).lower():
            raise
    _ensure_memory_scope_column(engine)
    _ensure_memory_enrichment_columns(engine)
    _ensure_memory_confidence_column(engine)
    _ensure_memory_indexes(engine)
    _ensure_memory_fts(engine)
    _ensure_chat_trace_indexes(engine)
    _ensure_short_long_memory_schema(engine)
    return engine, SessionLocal


def _ensure_memory_scope_column(engine) -> None:
    if not MEMORY_SQLITE_URL.startswith(SQLITE_URL_PREFIX):
        return
    with engine.begin() as conn:
        rows = conn.execute(sql_text(MEMORY_RECORDS_TABLE_INFO_SQL)).fetchall()
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


def _ensure_memory_enrichment_columns(engine) -> None:
    if not MEMORY_SQLITE_URL.startswith(SQLITE_URL_PREFIX):
        return
    with engine.begin() as conn:
        rows = conn.execute(sql_text(MEMORY_RECORDS_TABLE_INFO_SQL)).fetchall()
        if not rows:
            return
        cols = {r[1] for r in rows}
        if "category" not in cols:
            conn.execute(
                sql_text(
                    "ALTER TABLE memory_records "
                    "ADD COLUMN category VARCHAR(64) NOT NULL DEFAULT 'general'"
                )
            )
        if "structured_data" not in cols:
            conn.execute(
                sql_text(
                    "ALTER TABLE memory_records "
                    "ADD COLUMN structured_data TEXT NOT NULL DEFAULT '{}'"
                )
            )


def _ensure_memory_indexes(engine) -> None:
    if not MEMORY_SQLITE_URL.startswith(SQLITE_URL_PREFIX):
        return
    with engine.begin() as conn:
        conn.execute(
            sql_text(
                "CREATE INDEX IF NOT EXISTS ix_memory_scope_created_at "
                "ON memory_records(memory_scope, created_at DESC)"
            )
        )
        conn.execute(
            sql_text(
                "CREATE INDEX IF NOT EXISTS ix_memory_scope_source_created_at "
                "ON memory_records(memory_scope, source, created_at DESC)"
            )
        )


def _ensure_memory_confidence_column(engine) -> None:
    if not MEMORY_SQLITE_URL.startswith(SQLITE_URL_PREFIX):
        return
    with engine.begin() as conn:
        rows = conn.execute(sql_text(MEMORY_RECORDS_TABLE_INFO_SQL)).fetchall()
        if not rows:
            return
        cols = {r[1] for r in rows}
        if "confidence" in cols:
            return
        conn.execute(
            sql_text(
                "ALTER TABLE memory_records "
                "ADD COLUMN confidence FLOAT NOT NULL DEFAULT 0.5"
            )
        )


def _ensure_chat_trace_indexes(engine) -> None:
    if not MEMORY_SQLITE_URL.startswith(SQLITE_URL_PREFIX):
        return
    with engine.begin() as conn:
        conn.execute(
            sql_text(
                "CREATE INDEX IF NOT EXISTS ix_chat_trace_scope_created_at "
                "ON chat_trace_records(memory_scope, created_at DESC)"
            )
        )
        conn.execute(
            sql_text(
                "CREATE INDEX IF NOT EXISTS ix_chat_trace_request_id "
                "ON chat_trace_records(request_id)"
            )
        )


def _ensure_memory_fts(engine) -> None:
    if not MEMORY_SQLITE_URL.startswith(SQLITE_URL_PREFIX):
        return
    with engine.begin() as conn:
        created = False
        for tokenizer in ("porter", "unicode61", ""):
            try:
                token_clause = f", tokenize='{tokenizer}'" if tokenizer else ""
                conn.execute(
                    sql_text(
                        "CREATE VIRTUAL TABLE IF NOT EXISTS memory_records_fts "
                        f"USING fts5(text, content='memory_records', content_rowid='rowid'{token_clause})"
                    )
                )
                created = True
                break
            except Exception:
                continue
        if not created:
            return
        conn.execute(
            sql_text(
                "CREATE TRIGGER IF NOT EXISTS memory_records_ai AFTER INSERT ON memory_records BEGIN "
                "INSERT INTO memory_records_fts(rowid, text) VALUES (new.rowid, new.text); "
                "END"
            )
        )
        conn.execute(
            sql_text(
                "CREATE TRIGGER IF NOT EXISTS memory_records_ad AFTER DELETE ON memory_records BEGIN "
                "INSERT INTO memory_records_fts(memory_records_fts, rowid, text) VALUES ('delete', old.rowid, old.text); "
                "END"
            )
        )
        conn.execute(
            sql_text(
                "CREATE TRIGGER IF NOT EXISTS memory_records_au AFTER UPDATE ON memory_records BEGIN "
                "INSERT INTO memory_records_fts(memory_records_fts, rowid, text) VALUES ('delete', old.rowid, old.text); "
                "INSERT INTO memory_records_fts(rowid, text) VALUES (new.rowid, new.text); "
                "END"
            )
        )
        # Ensure existing rows are indexed.
        conn.execute(sql_text("INSERT INTO memory_records_fts(memory_records_fts) VALUES ('rebuild')"))


def _ensure_short_long_memory_schema(engine) -> None:
    """
    Additive, non-breaking schema for normalized memory architecture.

    Existing runtime still uses legacy tables (`memory_records`, `chat_trace_records`).
    These new tables are created in parallel so code can migrate safely in phases.
    """
    with engine.begin() as conn:
        conn.execute(
            sql_text(
                """
                CREATE TABLE IF NOT EXISTS short_traces (
                    id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    memory_scope TEXT NOT NULL DEFAULT 'global',
                    user_message TEXT NOT NULL,
                    assistant_response TEXT NOT NULL,
                    model_used TEXT NOT NULL,
                    retrieved_memory_ids TEXT NOT NULL DEFAULT '[]',
                    retrieval_method TEXT NOT NULL DEFAULT 'none'
                        CHECK (retrieval_method IN ('vector','fts','structured','hybrid','none')),
                    confidence_score FLOAT NOT NULL DEFAULT 0.5
                        CHECK (confidence_score >= 0.0 AND confidence_score <= 1.0),
                    latency_ms INTEGER NOT NULL DEFAULT 0
                        CHECK (latency_ms >= 0),
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        conn.execute(
            sql_text(
                """
                CREATE TABLE IF NOT EXISTS short_retrieval_logs (
                    id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    memory_scope TEXT NOT NULL DEFAULT 'global',
                    query_text TEXT NOT NULL,
                    retrieved_ids TEXT NOT NULL DEFAULT '[]',
                    method_used TEXT NOT NULL
                        CHECK (method_used IN ('vector','fts','structured','hybrid')),
                    score_distribution TEXT NOT NULL DEFAULT '{}',
                    confidence_score FLOAT NOT NULL DEFAULT 0.5
                        CHECK (confidence_score >= 0.0 AND confidence_score <= 1.0),
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        conn.execute(
            sql_text(
                """
                CREATE TABLE IF NOT EXISTS short_memory_queue (
                    id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    memory_scope TEXT NOT NULL DEFAULT 'global',
                    raw_content TEXT NOT NULL,
                    extraction_status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (extraction_status IN ('pending','processed','rejected')),
                    importance_score FLOAT NOT NULL DEFAULT 0.0
                        CHECK (importance_score >= 0.0 AND importance_score <= 1.0),
                    confidence_score FLOAT NOT NULL DEFAULT 0.5
                        CHECK (confidence_score >= 0.0 AND confidence_score <= 1.0),
                    dedupe_fingerprint TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    processed_at DATETIME
                )
                """
            )
        )
        conn.execute(
            sql_text(
                """
                CREATE TABLE IF NOT EXISTS long_entities (
                    id TEXT PRIMARY KEY,
                    memory_scope TEXT NOT NULL DEFAULT 'global',
                    entity_type TEXT NOT NULL,
                    canonical_name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    importance_score FLOAT NOT NULL DEFAULT 0.5
                        CHECK (importance_score >= 0.0 AND importance_score <= 1.0),
                    confidence_score FLOAT NOT NULL DEFAULT 0.5
                        CHECK (confidence_score >= 0.0 AND confidence_score <= 1.0),
                    dedupe_key TEXT NOT NULL,
                    source_trace_id TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(memory_scope, dedupe_key)
                )
                """
            )
        )
        conn.execute(
            sql_text(
                """
                CREATE TABLE IF NOT EXISTS long_attributes (
                    id TEXT PRIMARY KEY,
                    entity_id TEXT NOT NULL,
                    attribute_key TEXT NOT NULL,
                    attribute_value TEXT NOT NULL,
                    value_type TEXT NOT NULL
                        CHECK (value_type IN ('string','number','boolean','json','date')),
                    confidence_score FLOAT NOT NULL DEFAULT 0.5
                        CHECK (confidence_score >= 0.0 AND confidence_score <= 1.0),
                    source_trace_id TEXT,
                    source_queue_id TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (entity_id) REFERENCES long_entities(id) ON DELETE CASCADE
                )
                """
            )
        )
        conn.execute(
            sql_text(
                """
                CREATE TABLE IF NOT EXISTS long_relationships (
                    id TEXT PRIMARY KEY,
                    from_entity_id TEXT NOT NULL,
                    to_entity_id TEXT NOT NULL,
                    relation_type TEXT NOT NULL,
                    confidence_score FLOAT NOT NULL DEFAULT 0.5
                        CHECK (confidence_score >= 0.0 AND confidence_score <= 1.0),
                    source_trace_id TEXT,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (from_entity_id) REFERENCES long_entities(id) ON DELETE CASCADE,
                    FOREIGN KEY (to_entity_id) REFERENCES long_entities(id) ON DELETE CASCADE,
                    CHECK (from_entity_id <> to_entity_id),
                    UNIQUE (from_entity_id, to_entity_id, relation_type)
                )
                """
            )
        )
        conn.execute(
            sql_text(
                """
                CREATE TABLE IF NOT EXISTS long_embeddings (
                    id TEXT PRIMARY KEY,
                    entity_id TEXT NOT NULL,
                    embedding_vector BLOB,
                    embedding_ref TEXT,
                    model_name TEXT NOT NULL,
                    confidence_score FLOAT NOT NULL DEFAULT 0.5
                        CHECK (confidence_score >= 0.0 AND confidence_score <= 1.0),
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (entity_id) REFERENCES long_entities(id) ON DELETE CASCADE
                )
                """
            )
        )
        conn.execute(
            sql_text(
                """
                CREATE TABLE IF NOT EXISTS long_memory_fts_source (
                    entity_id TEXT PRIMARY KEY,
                    memory_scope TEXT NOT NULL DEFAULT 'global',
                    canonical_name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    attributes_text TEXT NOT NULL DEFAULT '',
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (entity_id) REFERENCES long_entities(id) ON DELETE CASCADE
                )
                """
            )
        )

        conn.execute(sql_text("CREATE INDEX IF NOT EXISTS ix_short_traces_scope_created ON short_traces(memory_scope, created_at DESC)"))
        conn.execute(sql_text("CREATE INDEX IF NOT EXISTS ix_short_traces_trace_id ON short_traces(trace_id)"))
        conn.execute(sql_text("CREATE INDEX IF NOT EXISTS ix_short_retrieval_logs_scope_created ON short_retrieval_logs(memory_scope, created_at DESC)"))
        conn.execute(sql_text("CREATE INDEX IF NOT EXISTS ix_short_retrieval_logs_trace_id ON short_retrieval_logs(trace_id)"))
        conn.execute(sql_text("CREATE INDEX IF NOT EXISTS ix_short_memory_queue_status_created ON short_memory_queue(extraction_status, created_at)"))
        conn.execute(sql_text("CREATE INDEX IF NOT EXISTS ix_short_memory_queue_scope_status_created ON short_memory_queue(memory_scope, extraction_status, created_at)"))
        conn.execute(sql_text("CREATE INDEX IF NOT EXISTS ix_short_memory_queue_fingerprint ON short_memory_queue(dedupe_fingerprint)"))
        conn.execute(sql_text("CREATE INDEX IF NOT EXISTS ix_long_entities_scope_type ON long_entities(memory_scope, entity_type)"))
        conn.execute(sql_text("CREATE INDEX IF NOT EXISTS ix_long_entities_scope_name ON long_entities(memory_scope, canonical_name)"))
        conn.execute(sql_text("CREATE INDEX IF NOT EXISTS ix_long_entities_confidence_importance ON long_entities(confidence_score DESC, importance_score DESC)"))
        conn.execute(sql_text("CREATE INDEX IF NOT EXISTS ix_long_attributes_entity_key ON long_attributes(entity_id, attribute_key)"))
        conn.execute(sql_text("CREATE INDEX IF NOT EXISTS ix_long_attributes_key_value ON long_attributes(attribute_key, attribute_value)"))
        conn.execute(sql_text("CREATE INDEX IF NOT EXISTS ix_long_relationships_from_type ON long_relationships(from_entity_id, relation_type)"))
        conn.execute(sql_text("CREATE INDEX IF NOT EXISTS ix_long_relationships_to_type ON long_relationships(to_entity_id, relation_type)"))
        conn.execute(sql_text("CREATE INDEX IF NOT EXISTS ix_long_embeddings_entity_model ON long_embeddings(entity_id, model_name)"))
        conn.execute(sql_text("CREATE INDEX IF NOT EXISTS ix_long_memory_fts_source_scope ON long_memory_fts_source(memory_scope)"))

        conn.execute(
            sql_text(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS long_memory_fts
                USING fts5(
                    canonical_name,
                    description,
                    attributes_text,
                    content='long_memory_fts_source',
                    content_rowid='rowid',
                    tokenize='unicode61'
                )
                """
            )
        )
        conn.execute(
            sql_text(
                """
                CREATE TRIGGER IF NOT EXISTS long_memory_fts_source_ai
                AFTER INSERT ON long_memory_fts_source BEGIN
                    INSERT INTO long_memory_fts(rowid, canonical_name, description, attributes_text)
                    VALUES (new.rowid, new.canonical_name, new.description, new.attributes_text);
                END
                """
            )
        )
        conn.execute(
            sql_text(
                """
                CREATE TRIGGER IF NOT EXISTS long_memory_fts_source_ad
                AFTER DELETE ON long_memory_fts_source BEGIN
                    INSERT INTO long_memory_fts(long_memory_fts, rowid, canonical_name, description, attributes_text)
                    VALUES ('delete', old.rowid, old.canonical_name, old.description, old.attributes_text);
                END
                """
            )
        )
        conn.execute(
            sql_text(
                """
                CREATE TRIGGER IF NOT EXISTS long_memory_fts_source_au
                AFTER UPDATE ON long_memory_fts_source BEGIN
                    INSERT INTO long_memory_fts(long_memory_fts, rowid, canonical_name, description, attributes_text)
                    VALUES ('delete', old.rowid, old.canonical_name, old.description, old.attributes_text);
                    INSERT INTO long_memory_fts(rowid, canonical_name, description, attributes_text)
                    VALUES (new.rowid, new.canonical_name, new.description, new.attributes_text);
                END
                """
            )
        )

