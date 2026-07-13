# Hybrid AI Gateway — Data Model

Version: 1.0

Last reviewed: 13 July 2026

Status: companion schema and lifecycle contract; Implemented / Target / Gap labeled against repository evidence

## 1. Purpose

This document owns **schemas, authority rules, retention, migrations, and backup scope** for gateway data.

Authorities:

| Topic | Source of truth |
|---|---|
| Pipeline write/retrieve semantics | `docs/architecture/AI_PIPELINE.md` §8–11 |
| Product entities and DATA-* rules | `docs/PRD.md` §13 |
| System storage overview | `docs/ARCHITECTURE.md` §6 |
| Observed schema | `memory/models.py`, `memory/db.py` |

Detailed retrieval ranking belongs in `MEMORY_AND_RAG.md`. Public HTTP shapes belong in `API_DESIGN.md`.

## 2. Authority Model

| Store | Role | Status |
|---|---|---|
| Relational SQLite (or Postgres profile) | **Authoritative** for memory records, short-term traces, long-term entities/attributes | Implemented |
| FAISS / pgvector indexes | **Derived** from authoritative records; rebuildable | Implemented |
| FTS tables | **Derived** lexical index | Implemented |
| In-memory approval store | Process-local; not durable authority | Implemented Gap vs Target durable approvals |
| Evidence bundle | Request-scoped reference contract | Target (`AI_PIPELINE.md` §11) |

**Rule (FR-MEM-001 / DATA-003):** commit authoritative writes before treating derived indexing as complete. Embedding failure must not delete accepted long-term facts (`AI_PIPELINE.md` §8.5).

## 3. Core Entities (Product Contract)

From PRD §13.1:

| Entity | Minimum data | Lifecycle | Status |
|---|---|---|---|
| Gateway configuration revision | schema version, non-secret values, capabilities, timestamps | Secret refs only; rollback | Target |
| Provider profile | type, base URLs, credential reference, capability map | NVIDIA in MVP | Target persistence; env-based today |
| Memory scope | stable ID, owner/actor when applicable, policy | Global default for trusted single-user only | Partial (app-level selector) |
| Memory record | ID, scope, text, source, category, importance/confidence, structured data, timestamps, extraction version | Authoritative and deletable | Implemented (`memory_records`) |
| Long-term attribute | scope, entity/category, key, value, source memory ID, confidence | Correctable; conflict policy required | Implemented (`long_attributes`) |
| Short-term trace | request/trace ID, scope, user/assistant text, route, retrieval method, status, timestamps | TTL/count bounded | Implemented (`short_traces`, legacy `chat_trace_records`) |
| Retrieval log | request, scope, query fingerprint, selected IDs, scores, method, timing | Operational retention | Implemented (`short_retrieval_logs`) |
| Approval | ID, actor, tool/version, arg hash, scope, risk, state, expiry | One-time; immutable after decision | Gap: process-local (`permissions/approvals.py`) |
| Tool execution | approval ref, request ID, capability, sanitized I/O, state, duration | Audit retention | Partial via API responses/logs |
| Provider request trace | gateway request ID, provider, model, modality, timing, outcome | No raw secrets/content by default | Partial / Target |

## 4. Implemented Relational Schema

### 4.1 ORM tables (`memory/models.py`)

**`memory_records`**

| Column | Notes |
|---|---|
| `id` | Primary key |
| `user_id`, `memory_scope` | Scope selectors (not authenticated tenancy) |
| `text` | Stored content |
| `source`, `category` | Provenance and type |
| `structured_data` | JSON string |
| `importance`, `confidence` | Float scores |
| `created_at` | UTC timestamp |

**`chat_trace_records`**

Legacy exact chat audit: `request_id`, scope, `user_text`, `assistant_text`, `model`, `retrieval_summary`, timestamps.

### 4.2 Additive short-term tables (`memory/db.py`)

| Table | Purpose |
|---|---|
| `short_traces` | Exact user/assistant text, model, retrieved IDs, retrieval method, confidence, latency |
| `short_retrieval_logs` | Per-retrieval query text, IDs, method, score distribution |
| `short_memory_queue` | Extraction queue (`pending` / `processed` / `rejected`) |
| `short_runtime_metrics` | Runtime counters |
| `short_scope_resolution_events` | Scope resolution audit |

### 4.3 Additive long-term tables

| Table | Purpose |
|---|---|
| `long_entities` | Canonical entities per scope |
| `long_attributes` | Key/value attributes on entities |
| `long_relationships` | Entity relationships |
| `long_embeddings` | Embedding status/payload linkage |
| `long_memory_fts_source` + FTS | Lexical index source |

### 4.4 Vector stores

| Backend | Config | Status |
|---|---|---|
| FAISS | `MEMORY_VECTOR_BACKEND=faiss`, `MEMORY_VECTOR_PATH` | Default Implemented |
| pgvector | `MEMORY_VECTOR_BACKEND=pgvector`, Postgres URL | Optional Implemented |

Vector rows must reference authoritative IDs (DATA-004). Dimension/model mismatch must be detected (FR-MEM-013).

## 5. Target Short-Term Trace Fields

From `AI_PIPELINE.md` §8.1 — store exact accepted user text and final assistant text plus:

- request/trace ID, conversation/session ID when available
- memory scope
- input and response modality (Target)
- selected model alias
- retrieved memory/source IDs
- completion state: complete, cancelled, partial, failed (Target completeness)
- confidence and latency metadata

Do not store raw audio by default.

### Retention

| Setting | Target production | Current default Gap |
|---|---|---|
| `SHORT_TERM_RETENTION_HOURS` | `24` | Implemented |
| `SHORT_TERM_CLEAR_ON_RESTART` | `false` | Often `true` (dev/test); production should retain unexpired rows (FR-MEM-010) |

Count caps remain a second bound against unbounded growth.

## 6. Target Long-Term Classifier Schema

Classifier JSON (Target contract; classification path partially Implemented):

```json
{
  "should_store": true,
  "importance_score": 0.86,
  "confidence": 0.94,
  "category": "work",
  "sensitivity": "normal",
  "reason_code": "durable_user_fact",
  "facts": [
    {
      "subject": "user",
      "predicate": "job_title",
      "value": "Junior Software Engineer II",
      "canonical_text": "The user works as a Junior Software Engineer II.",
      "valid_from": null,
      "valid_until": null
    }
  ]
}
```

Deterministic validation must reject malformed, secret-like, low-confidence, and low-importance outputs before promotion (FR-MEM-016).

## 7. Evidence Bundle Shape (Target)

Request-scoped, not a durable table by default (`AI_PIPELINE.md` §11):

- `conversation_context`, `short_term_memory`, `long_term_memory`, `internet_sources`, `tool_results`
- `evidence_status`, `limitations`
- per-item provenance, scores, scope, sensitivity

## 8. Integrity and Migration Requirements

| ID | Requirement | Status |
|---|---|---|
| DATA-001 | Versioned migrations; runtime `create_all` alone not production-acceptable | Gap |
| DATA-002 | FKs, uniqueness, scope constraints, indexes | Partial |
| DATA-003 | Authoritative commit before derived index complete | Target / Partial |
| DATA-004 | Derived entries reference authoritative IDs + reconciliation | Partial |
| DATA-005 | Queue jobs idempotent or deduplicated | Partial |
| DATA-006 | Backup covers relational memory, config, approvals/audit, Open WebUI state; vectors rebuildable | Target |
| DATA-007 | Deletion idempotent; derived data removed/tombstoned | Partial |
| DATA-008 | Paths, permissions, retention, disk-full documented/tested | Gap |
| DATA-009 | Dev/test records must not use real personal data | Process requirement |

## 9. Approvals Persistence

| Aspect | Implemented | Target |
|---|---|---|
| Storage | In-process `ApprovalStore` | Durable SQLite (or equivalent) records (OD-006) |
| Binding | Approval ID + argument hash | Actor/client, tool version, scope, risk, expiry, one-time use |
| Audit | Limited | Immutable decision + execution evidence |

## 10. Backup and Restore Scope

Must cover (DATA-006 / PRD §17.3):

- Relational memory databases
- Configuration (non-secret) and secret-management procedure
- Approvals/audit when durable
- Open WebUI volume state as applicable
- Vector indexes may be rebuilt via reindex

## 11. Dual-Path Legacy Note

**Gap (OD-010):** legacy `memory_records` / facade paths coexist with short-term and long-term entity tables. Target architecture selects the new repository/service model and documents migration/retirement. Until then, deletion and reindex must keep relational and derived semantics aligned.

## 12. Related Documents

- `docs/architecture/MEMORY_AND_RAG.md`
- `docs/architecture/AI_PIPELINE.md`
- `docs/architecture/TOOL_PERMISSION_MODEL.md`
- `docs/engineering/CONFIGURATION.md`
