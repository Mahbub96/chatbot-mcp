# Hybrid AI Gateway — Functional Requirements Catalog

Version: 1.0

Last reviewed: 13 July 2026

Status: extracted from `docs/PRD.md` §7–12; status labels are engineering annotations against repository evidence, not a change to PRD priority

Authority: `docs/PRD.md` remains the product requirements source of truth. Pipeline behavior: `docs/architecture/AI_PIPELINE.md`.

Status vocabulary: **Implemented** (baseline code), **Partial**, **Target**, **Gap**, **Deferred** (explicitly out of Phase 1).

## 1. Gateway Lifecycle and Configuration

| ID | Priority | Requirement | Status |
|---|---|---|---|
| FR-GWY-001 | Must | Bind to `127.0.0.1` by default | Gap (`start.sh` binds `0.0.0.0`) |
| FR-GWY-002 | Must | Startup validates credentials, models, ports, paths, profiles before readiness | Partial |
| FR-GWY-003 | Must | Optional deps reported available/unavailable/degraded without blocking core chat | Partial |
| FR-GWY-004 | Must | Typed, validated, centrally documented config; no hard-coded secrets | Partial |
| FR-GWY-005 | Must | Graceful shutdown finishes/cancels bounded work, closes clients, safe derived state | Partial |
| FR-GWY-006 | Should | Preflight component matrix | Gap |
| FR-GWY-007 | Must | Publish build/config schema version and capability summary without secrets | Gap |

Detail: `docs/engineering/CONFIGURATION.md`, `docs/operations/LOCAL_SETUP.md`.

## 2. Chat Completions

| ID | Priority | Requirement | Status |
|---|---|---|---|
| FR-CHAT-001 | Must | OpenAI-compatible stream/non-stream subset on `/v1/chat/completions` | Partial |
| FR-CHAT-002 | Must | Defined streaming framing, terminal, errors, cancellation | Partial |
| FR-CHAT-003 | Must | Validate roles, content, size, modality, capability | Partial |
| FR-CHAT-004 | Must | Client cancellation stops upstream/downstream promptly | Gap/Partial |
| FR-CHAT-005 | Must | Provider failures → stable codes; no credential leak | Partial |
| FR-CHAT-006 | Must | Chat success not lost solely due to async memory failure | Partial |
| FR-CHAT-007 | Should | Normalize usage metadata; never fabricate tokens | Partial |
| FR-CHAT-008 | Must | Document/test/deprecate `POST /chat` | Gap |
| FR-CHAT-009 | Should | Humanization transparent; no safety/tool/schema override | Partial |
| FR-CHAT-010 | Must | Text enters canonical AI pipeline; shared request ID | Partial |
| FR-CHAT-011 | Must | Local evidence sufficiency before external search | Target / Gap |
| FR-CHAT-012 | Must | Distinguish evidence, inference, no-result, failure | Target / Gap |
| FR-CHAT-013 | Must | Future STT/TTS wrap text-first pipeline | Deferred (OD-018) |

Detail: `docs/architecture/API_DESIGN.md`, `docs/architecture/AI_PIPELINE.md`.

## 3. Model Discovery

| ID | Priority | Requirement | Status |
|---|---|---|---|
| FR-MOD-001 | Must | List only configured eligible gateway models | Partial |
| FR-MOD-002 | Must | Distinguish gateway aliases from provider IDs | Target (OD-004) |
| FR-MOD-003 | Should | Capability metadata matrix | Gap |
| FR-MOD-004 | Must | Model retirement/denial as operator diagnostic, not user-input fault | Gap |

## 4. Provider Boundary

| ID | Priority | Requirement | Status |
|---|---|---|---|
| FR-PRV-001 | Must | Secrets from approved config; never returned | Partial |
| FR-PRV-002 | Must | Bounded budgets by modality | Partial |
| FR-PRV-003 | Must | Retry only safe failures | Gap |
| FR-PRV-004 | Must | Fallback preserves modality | Partial (vision guard) |
| FR-PRV-005 | Must | Disclose provider egress | Partial (docs) |
| FR-PRV-006 | Should | Cached/bounded provider health | Gap |
| FR-PRV-007 | Must | Reject malformed success responses | Partial |

Detail: `docs/architecture/SYSTEM_DESIGN.md`.

## 5. Routing

| ID | Priority | Requirement | Status |
|---|---|---|---|
| FR-RTE-001 | Must | Deterministic routing | Implemented (heuristics) |
| FR-RTE-002 | Must | Modality precedes language/code | Implemented |
| FR-RTE-003 | Must | Intent advisory only | Partial |
| FR-RTE-004 | Must | Explicit fallback or config error | Partial |
| FR-RTE-005 | Should | Sanitized reason codes | Gap |
| FR-RTE-006 | Must | Code/Bangla regression fixtures | Partial |
| FR-RTE-007 | Must | Select route before provider; stable unless approved fallback | Implemented |

## 6. Memory and Retrieval

| ID | Priority | Requirement | Status |
|---|---|---|---|
| FR-MEM-001 | Must | Relational authoritative; vectors derived | Implemented |
| FR-MEM-002 | Must | Explicit scope before read/write | Implemented |
| FR-MEM-003 | Must | Auto-store filters low-signal/unsafe | Partial |
| FR-MEM-004 | Must | Normalized durable facts, not blind utterance copies | Partial |
| FR-MEM-005 | Must | Scoped retrieval + sufficiency + budget | Partial (sufficiency Gap) |
| FR-MEM-006 | Must | No personal cross-scope/web fallback by default | Partial |
| FR-MEM-007 | Must | Writes/embeddings off fast path | Implemented |
| FR-MEM-008 | Must | Queue failure → known delivery state; no duplicate facts | Partial |
| FR-MEM-009 | Must | List/search/add/delete/reindex | Implemented |
| FR-MEM-010 | Must | TTL/count limits; production retains across restart | Gap (clear-on-restart default) |
| FR-MEM-011 | Should | Hybrid ranking evaluated | Partial |
| FR-MEM-012 | Must | Memory as untrusted reference data | Partial / Target |
| FR-MEM-013 | Must | Atomic/recoverable index; dimension mismatch detect | Partial |
| FR-MEM-014 | Must | No personal derived data in source control | Gap risk |
| FR-MEM-015 | Must | Local retrieval before internet fallback | Target (search Deferred) |
| FR-MEM-016 | Must | Deterministic validation after AI classification | Partial |

Detail: `docs/architecture/MEMORY_AND_RAG.md`, `DATA_MODEL.md`.

## 7. MCP, Tools, and Approvals

| ID | Priority | Requirement | Status |
|---|---|---|---|
| FR-MCP-001 | Must | Discovery of registered enabled tools | Implemented |
| FR-MCP-002 | Must | Validate args before approval/execution | Partial |
| FR-MCP-003 | Must | Deterministic policy | Implemented |
| FR-MCP-004 | Must | Bound actor, tool version, args, expiry, one-time | Gap |
| FR-MCP-005 | Must | Rejection final; no side effects | Partial |
| FR-MCP-006 | Must | Timeout, limits, cwd, env allowlist, cleanup | Partial |
| FR-MCP-007 | Must | Canonical paths under approved root | Partial |
| FR-MCP-008 | Must | Explicit shell policy; no unsafe interpolation | Gap |
| FR-MCP-009 | Must | Full state distinction | Partial |
| FR-MCP-010 | Must | Success with postconditions/evidence | Partial |
| FR-MCP-011 | Should | Undo/trash for reversible mutations | Gap |
| FR-MCP-012 | Must | Redact secrets in output/audit | Partial |
| FR-MCP-013 | Must | Cursor bridge preserves approval semantics | Partial |
| FR-MCP-014 | Must | Max tool actions enforced by gateway | Gap |

Detail: `docs/architecture/TOOL_PERMISSION_MODEL.md`.

## 8. Multimodal and Images

| ID | Priority | Requirement | Status |
|---|---|---|---|
| FR-MM-001 | Must | Validate schemes, MIME, size, redirects before materialize | Partial |
| FR-MM-002 | Must | Deny private/loopback/metadata/local by default | Gap |
| FR-MM-003 | Must | Trusted local files only via approved roots | Partial |
| FR-MM-004 | Must | Video limits + temp cleanup | Partial |
| FR-MM-005 | Must | No unsafe shell for media binaries | Partial |
| FR-MM-006 | Must | Route only to eligible vision model | Implemented |
| FR-MM-007 | Must | Media in egress disclosure | Partial (docs) |
| FR-MM-008 | Should | YouTube fallback distinguish frames vs metadata | Partial |
| FR-IMG-001 | Must | Validate gen/edit endpoints and errors | Partial |
| FR-IMG-002 | Must | No unexpected durable persistence of outputs | Partial |
| FR-IMG-003 | Should | Normalized alias/correlation metadata | Gap |

## 9. Open WebUI

| ID | Priority | Requirement | Status |
|---|---|---|---|
| FR-UI-001 | Must | Pin/document tested image digest | Gap (`:main` floating) |
| FR-UI-002 | Must | Document volumes, ports, base URL, auth | Partial |
| FR-UI-003 | Must | Gateway readiness before UI-ready messaging | Implemented in `start.sh` wait |
| FR-UI-004 | Must | Document unsupported UI features | Gap |
| FR-UI-005 | Should | Integration smoke tests | Gap |

## 10. Cursor MCP Bridge

| ID | Priority | Requirement | Status |
|---|---|---|---|
| FR-CUR-001 | Must | Health, discovery, execute, approvals with typed results | Partial |
| FR-CUR-002 | Must | Configurable validated gateway URL/timeouts | Partial |
| FR-CUR-003 | Must | Structured JSON args validated both sides | Partial |
| FR-CUR-004 | Must | Do not log sensitive args by default | Partial |

## 11. Direct API Clients

Target expectations from PRD §12.3: discover aliases/capabilities; publish OpenAI subset and deviations; map client model IDs through policy; prefer idempotency keys for consequential ops; accept or generate request IDs consistently.

## 12. Related Documents

- `docs/requirements/ACCEPTANCE_CRITERIA.md`
- `docs/requirements/NON_FUNCTIONAL_REQUIREMENTS.md`
- `docs/requirements/SECURITY_REQUIREMENTS.md`
- `docs/PRD.md`
