from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, text as sql_text

from config import PGVECTOR_HNSW_EF_CONSTRUCTION, PGVECTOR_HNSW_M


class PgVectorStore:
    def __init__(self, *, engine: Engine, dim: int):
        self._engine = engine
        self.dim = dim
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        if self._engine.dialect.name != "postgresql":
            raise RuntimeError("PgVectorStore requires a PostgreSQL database URL.")
        with self._engine.begin() as conn:
            conn.execute(sql_text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.execute(
                sql_text(
                    f"""
                    CREATE TABLE IF NOT EXISTS memory_vector_embeddings (
                        memory_id VARCHAR(64) PRIMARY KEY REFERENCES memory_records(id) ON DELETE CASCADE,
                        memory_scope VARCHAR(128) NOT NULL,
                        embedding vector({self.dim}) NOT NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
            )
            conn.execute(
                sql_text(
                    "CREATE INDEX IF NOT EXISTS ix_memory_vector_embeddings_scope "
                    "ON memory_vector_embeddings(memory_scope)"
                )
            )
            conn.execute(
                sql_text(
                    f"""
                    CREATE INDEX IF NOT EXISTS ix_memory_vector_embeddings_hnsw
                    ON memory_vector_embeddings
                    USING hnsw (embedding vector_cosine_ops)
                    WITH (m = {PGVECTOR_HNSW_M}, ef_construction = {PGVECTOR_HNSW_EF_CONSTRUCTION})
                    """
                )
            )

    def _vector_literal(self, embedding: list[float]) -> str:
        return "[" + ",".join(f"{float(x):.8f}" for x in embedding) + "]"

    def add(self, *, memory_id: str, memory_scope: str, embedding: list[float]) -> None:
        vector_lit = self._vector_literal(embedding)
        with self._engine.begin() as conn:
            conn.execute(
                sql_text(
                    """
                    INSERT INTO memory_vector_embeddings(memory_id, memory_scope, embedding)
                    VALUES (:memory_id, :memory_scope, CAST(:embedding AS vector))
                    ON CONFLICT (memory_id)
                    DO UPDATE SET
                        memory_scope = EXCLUDED.memory_scope,
                        embedding = EXCLUDED.embedding
                    """
                ),
                {
                    "memory_id": memory_id,
                    "memory_scope": memory_scope,
                    "embedding": vector_lit,
                },
            )

    def search(self, *, memory_scope: str, embedding: list[float], top_k: int) -> list[dict[str, Any]]:
        vector_lit = self._vector_literal(embedding)
        with self._engine.begin() as conn:
            rows = conn.execute(
                sql_text(
                    """
                    SELECT memory_id, 1 - (embedding <=> CAST(:embedding AS vector)) AS score
                    FROM memory_vector_embeddings
                    WHERE memory_scope = :memory_scope
                    ORDER BY embedding <=> CAST(:embedding AS vector)
                    LIMIT :top_k
                    """
                ),
                {
                    "embedding": vector_lit,
                    "memory_scope": memory_scope,
                    "top_k": int(max(1, top_k)),
                },
            ).mappings().all()
        return [{"id": str(row["memory_id"]), "score": float(row["score"] or 0.0)} for row in rows]

    def rebuild(self, *, rows: list[dict[str, Any]], embed_fn) -> None:
        scopes = sorted({str(r.get("memory_scope") or "").strip() for r in rows if str(r.get("memory_scope") or "").strip()})
        with self._engine.begin() as conn:
            if scopes:
                conn.execute(
                    sql_text("DELETE FROM memory_vector_embeddings WHERE memory_scope = ANY(:scopes)"),
                    {"scopes": scopes},
                )
            else:
                conn.execute(sql_text("DELETE FROM memory_vector_embeddings"))
        for row in rows:
            self.add(
                memory_id=str(row["id"]),
                memory_scope=str(row["memory_scope"]),
                embedding=embed_fn(str(row["text"])),
            )

    def flush(self) -> None:
        return

