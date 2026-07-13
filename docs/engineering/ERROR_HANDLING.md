# Hybrid AI Gateway — Error Handling

Version: 1.0

Last reviewed: 13 July 2026

Status: taxonomy and mapping companion; Target stable codes vs Implemented `{"error": ...}` patterns

## 1. Purpose

Define gateway error categories, response shape, streaming termination, and isolation rules.

Authorities: PRD §14.2; API-003; FR-CHAT-005/006; `AI_PIPELINE.md` §10.5, §15; code: `gateway/helpers/http_utils.py`, routers/controllers.

## 2. Target Error Response Shape (API-003)

Every public error SHOULD include:

| Field | Meaning |
|---|---|
| `code` | Stable machine code |
| `message` | Safe operator/user message (no secrets/raw payloads) |
| HTTP status | Semantic status |
| `request_id` | Correlation ID |
| `retryable` | Whether client may retry |
| remediation | Optional next step |

**Implemented:** many paths return `{"error": "<message>"}` via `json_error`. Middleware 500 includes `request_id`. Full taxonomy Gap.

## 3. Target Taxonomy (PRD §14.2)

| Category | Example codes |
|---|---|
| Validation | `invalid_request`, `unsupported_field`, `payload_too_large`, `unsupported_modality` |
| Configuration | `provider_not_configured`, `model_not_configured`, `dependency_unavailable` |
| Authentication/policy | `unauthorized`, `forbidden`, `approval_required`, `approval_expired`, `approval_mismatch` |
| Provider | `provider_unauthorized`, `provider_rate_limited`, `provider_model_unavailable`, `provider_timeout`, `provider_error` |
| Memory | `memory_disabled`, `memory_scope_invalid`, `memory_backend_unavailable`, `memory_index_incompatible` |
| Media | `media_fetch_denied`, `media_fetch_failed`, `media_decode_failed`, `media_too_large` |
| Tool | `tool_not_found`, `tool_disabled`, `tool_timeout`, `tool_execution_failed`, `tool_postcondition_failed` |
| System | `not_ready`, `storage_full`, `internal_error`, `cancelled` |

## 4. Implemented HTTP Patterns

| Area | Typical statuses | Notes |
|---|---|---|
| Chat | 400, 429, 502 | Bad body; rate limit; upstream |
| Images | 400, 429, 502 | Similar |
| Readiness | 503 | `/health/ready` |
| Catch-all | 500 | Sanitized message + request_id |
| Memory / MCP | Often 200 + `success: false` | Gap vs API-003 |

No centralized FastAPI exception-handler registry yet (Gap).

## 5. Streaming Errors

Target (FR-CHAT-002): every stream has one terminal outcome; errors terminate the stream cleanly; no duplicate content. Client cancellation and upstream disconnect are first-class.

## 6. Isolation Rules

| Failure | Behavior |
|---|---|
| Async memory failure | Chat may succeed; memory failure separately observable (FR-CHAT-006, NFR-REL-001) |
| Long-term classifier failure | Answer normally; job retry/discard policy |
| Embedding failure | Keep relational fact; structured/lexical retrieval |
| Search failure vs no-result | Distinct codes/states (`AI_PIPELINE.md` §10.5) — Target |
| TTS failure | Return full text + warning — Target |
| Tool denial | No side effects; clear approval/policy state |

## 7. Provider Mapping

Distinguish invalid key, timeout, rate limit, retired/unavailable model, and provider 5xx (FR-CHAT-005, FR-MOD-004). Do not misreport provider issues as user validation errors.

## 8. Related Documents

- `docs/architecture/API_DESIGN.md`
- `docs/operations/TROUBLESHOOTING.md`
- `docs/architecture/AI_PIPELINE.md` §15
