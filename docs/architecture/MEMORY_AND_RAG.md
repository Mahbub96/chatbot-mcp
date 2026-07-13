# Hybrid AI Gateway — Memory and RAG

Version: 1.0

Last reviewed: 13 July 2026

Status: storage, retrieval, queue, and evaluation companion; pipeline authority remains `AI_PIPELINE.md`

## 1. Purpose

This document owns **memory taxonomy, extraction, ranking, queue semantics, migration, and evaluation**.

Authorities:

| Topic | Source of truth |
|---|---|
| Exact short-term / normalized long-term / sufficiency / search | `docs/architecture/AI_PIPELINE.md` |
| FR-MEM and quality measures | `docs/PRD.md` §9 |
| Schemas and migrations | `docs/architecture/DATA_MODEL.md` |
| Observed services | `memory/facade.py`, `memory/services/*`, `memory/pipelines/memory_pipeline.py` |

## 2. Memory Taxonomy (PRD §9.1)

| Lane | Content | Retention | Status |
|---|---|---|---|
| Short-term | Exact accepted user and assistant wording | TTL (24h target) + count caps | Implemented (restart-clear Gap) |
| Long-term | Normalized facts/preferences/relationships/events | Durable until delete/supersede | Partial / Target completeness |
| Profile / structured slots | Key attributes for recall | Durable | Partial |
| Derived vectors / FTS | Search indexes only | Rebuildable | Implemented |
| Evidence bundle | Per-request assembled references | Ephemeral | Target |

**Non-goals:** storing every utterance permanently; treating vectors as authoritative; using the answer model alone to enforce memory policy.

## 3. Principles

1. **Fast path:** user-visible response must not wait on long-term extraction, embedding, or index maintenance (`AI_PIPELINE.md` §3.1).
2. **Exact vs normalized:** short-term copies accepted wording; long-term stores structured facts (`§3.2`).
3. **Local before external:** scoped local retrieval before any internet fallback (`§3.3`; OD-017 deferred).
4. **Deterministic authority:** thresholds, scope, retention, and promotion rules live in application code (`§3.5`).

## 4. Write Paths

### 4.1 Short-term exact capture

**Implemented:** `MemoryService.log_chat_trace()` and `short_traces` / legacy `chat_trace_records`.

**Target:** complete before or alongside orchestration; failure may degrade but must be observable (FR-CHAT-006). Production default retains unexpired rows across ordinary restart (`SHORT_TERM_CLEAR_ON_RESTART=false`).

### 4.2 Long-term extraction

**Implemented:** `classify_memory_candidate()` / `ExtractionService`; async via `MemoryPipeline` (in-process or Redis/RQ).

**Target flow (`AI_PIPELINE.md` §8.2–8.4):**

1. Classifier returns structured JSON (`should_store`, scores, category, sensitivity, facts).
2. Deterministic validation rejects noise, secrets, low confidence/importance.
3. Deduplicate / conflict-handle in scope.
4. Commit relational fact.
5. Queue embedding/index update; relational remains authoritative on embed failure.

| Importance band | Default action |
|---|---|
| 0.00–0.39 | Do not store |
| 0.40–0.59 | Short-term only |
| 0.60–0.79 | Store if confidence/sensitivity pass |
| 0.80–1.00 | Store after validation; careful conflicts |

## 5. Retrieval Stage Order

**Target / largely Implemented in `RetrievalService`:**

1. Current conversation context
2. Scoped short-term memory
3. Scoped long-term structured facts
4. Scoped semantic vector search
5. Scoped lexical / FTS fallback
6. Deduplicate, filter, recency-weight, trim to context budget

**Hard rules:**

- Resolve explicit `memory_scope` before every read/write (FR-MEM-002).
- Cross-scope fallback must not become an identity bypass (FR-MEM-006).
- Personal-memory misses must not auto-trigger internet search (AI-PIPE-009).
- Injected memory is **untrusted reference data**, not instructions (FR-MEM-012).

## 6. Evidence Sufficiency (Target)

Gateway decides sufficiency before external search (`AI_PIPELINE.md` §9.3; FR-CHAT-011).

Example decision contract:

```json
{
  "local_evidence_found": true,
  "local_evidence_sufficient": false,
  "requires_current_information": true,
  "internet_search_eligible": true,
  "reason_code": "local_data_stale"
}
```

**Status:** Gap — memory is retrieved and injected, but formal sufficiency + search executor are not complete.

## 7. Internet Search Fallback

**Status:** Target / deferred from Phase 1 (OD-017). Intent label `internet_search` exists; no production provider.

Eligibility only when local evidence insufficient, request needs external/current info, network policy allows, privacy policy permits, and provider is ready. Search content is untrusted (AI-PIPE-010). Distinguish `search_not_allowed`, `search_not_configured`, `search_failed`, `search_no_results`, `search_results_found`.

## 8. Queue and Idempotency

| Concern | Requirement | Status |
|---|---|---|
| Off fast path | FR-MEM-007 | Implemented |
| Delivery state on failure | FR-MEM-008 | Partial |
| Idempotent jobs | DATA-005 | Partial |
| Backends | In-process default; Redis/RQ optional | Implemented |

## 9. Operator Lifecycle APIs

**Implemented routes:** list/add/search/stats/short-traces/delete/reindex under `/memory/*` (see `API_DESIGN.md`).

Deletion must remove or reconcile derived index entries (FR-MEM-009 / DATA-007).

## 10. Quality Measures (PRD §9.3)

Evaluate against labeled fixtures:

- Precision@K for retrieval
- Memory pollution (low-signal promotions)
- Cross-scope leakage (must be zero by default)
- Duplicate durable facts
- Personal→web search false triggers (must be zero)

## 11. Requirements Catalog Pointers

FR-MEM-001…016 are cataloged in `docs/requirements/FUNCTIONAL_REQUIREMENTS.md` with acceptance in `ACCEPTANCE_CRITERIA.md`. Pipeline acceptance AI-PIPE-002…007,014 live in `AI_PIPELINE.md` §19.

## 12. Migration and Consolidation

**Gap (OD-010):** dual legacy + short/long paths. Target: single service architecture, versioned migrations (DATA-001), documented retirement of legacy methods, and production default TTL retention across restart.

## 13. Related Documents

- `docs/architecture/AI_PIPELINE.md`
- `docs/architecture/DATA_MODEL.md`
- `docs/architecture/SYSTEM_DESIGN.md`
- `docs/planning/TECH_DEBT.md`
