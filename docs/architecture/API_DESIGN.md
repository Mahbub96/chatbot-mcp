# Hybrid AI Gateway — API Design

Version: 1.0

Last reviewed: 13 July 2026

Status: public route and contract companion; OpenAI-compatible subset vs gateway extensions distinguished

## 1. Purpose

This document owns **route contracts, streaming protocol, errors, pagination, and compatibility notes** including future search/STT/TTS schemas.

Authorities: `docs/PRD.md` §14 and Appendix A; `docs/architecture/AI_PIPELINE.md` (envelope, modality); `docs/ARCHITECTURE.md`; observed routers under `gateway/routers/`.

## 2. API Standards

| ID | Requirement | Status |
|---|---|---|
| API-001 | OpenAPI or documented SSE/MCP contract per public route | Partial |
| API-002 | Typed request/response models at trust boundaries | Gap (many loose dicts) |
| API-003 | Errors: stable code, safe message, HTTP status, request ID, retryability | Partial |
| API-004 | Validation limits (messages, text, media, tools, pagination) | Partial |
| API-005 | Streaming: content type, deltas, heartbeat, terminal, error end | Partial / Target formalization |
| API-006 | Compatibility aliases documented with deprecation policy | Gap for `/chat` |
| API-007 | Local routes not assumed safe without deployment auth policy | Gap (no client auth) |
| API-008 | Document OpenAI-compatible vs gateway-specific behavior | This document |
| API-009 | Versioning protects clients from breaking changes | Target |
| API-010 | Pagination: stable ordering, bounded limits | Partial |

## 3. Observed Endpoint Inventory (Implemented)

| Method | Path | Purpose | Compatibility |
|---|---|---|---|
| POST | `/v1/chat/completions` | Chat stream/non-stream | OpenAI-compatible subset |
| POST | `/chat` | Alias of chat completions | Gateway compatibility alias |
| GET | `/v1/models` | Model listing for clients/WebUI | OpenAI-compatible subset |
| POST | `/v1/images/generations` | Text-to-image | OpenAI-compatible proxy |
| POST | `/v1/images/edits` | Image edit | OpenAI-compatible proxy |
| GET | `/mcp/tools` | Tool discovery | Gateway / MCP-style |
| POST | `/mcp/execute` | Tool execution under policy | Gateway |
| GET | `/mcp/approvals` | Pending approvals | Gateway |
| POST | `/mcp/approve` | Approve/reject | Gateway |
| GET | `/memory/items` | List memory | Gateway |
| POST | `/memory/items` | Add memory | Gateway |
| POST | `/memory/store` | Add alias | Gateway |
| POST | `/memory/search` | Search memory | Gateway |
| GET | `/memory/stats` | Memory stats | Gateway |
| GET | `/memory/short-traces` | Recent short-term traces | Gateway |
| DELETE | `/memory/items/{item_id}` | Delete | Gateway |
| POST | `/memory/reindex` | Rebuild derived index | Gateway |
| GET | `/health/live` | Liveness | Gateway |
| GET | `/health/ready` | Readiness (503 if not ready) | Gateway |
| GET | `/health/routes` | Route manifest | Gateway |
| GET | `/metrics` | Prometheus text | Gateway |

**Gap:** no authentication on any route. Several MCP/memory failures return HTTP 200 with `{"success": false}` rather than 4xx — Target is stable error codes (API-003).

## 4. Chat Completions

### 4.1 Contract (FR-CHAT-001…013)

- Support documented OpenAI-compatible streaming and non-streaming fields; reject unsupported dangerous inputs clearly.
- Validate roles, content forms, size, modality, and model/capability compatibility before provider calls.
- Provider failures map to stable gateway errors without leaking credentials (FR-CHAT-005).
- Successful chat must not be silently lost solely because async memory fails (FR-CHAT-006).
- Text requests enter the canonical AI pipeline (`AI_PIPELINE.md`; FR-CHAT-010).

### 4.2 Streaming (Target formalization)

Define: event framing, delta ordering, single terminal outcome, error termination, client cancellation, upstream disconnect, optional heartbeat/status. No duplicate content on completion.

**Implemented:** SSE-style streaming exists; full protocol documentation and cancellation guarantees remain Target.

### 4.3 Compatibility alias

`POST /chat` must be documented, tested, or formally deprecated (FR-CHAT-008 / API-006).

## 5. Models

`GET /v1/models` must return only configured eligible gateway IDs and capabilities (FR-MOD-001…004). Distinguish public aliases from provider IDs (`SYSTEM_DESIGN.md`). Current listing is simplified for WebUI — Gap vs full capability matrix.

## 6. Images

`POST /v1/images/generations` and `/v1/images/edits` proxy configured NVIDIA models. Document limits, MIME/size policy, and correlation metadata (Target). OD-014 may keep or defer image routes from MVP after contract testing.

## 7. Memory Routes

Gateway-specific. Scope required for reads/writes. Soft-success JSON Gap noted above. Reindex rebuilds derived vectors from authoritative relational data.

## 8. MCP Routes

Discovery, execute, approvals, approve/reject. Approval-required tools must not execute until approval is granted and consumed (`TOOL_PERMISSION_MODEL.md`). Cursor bridge must not bypass gateway policy (FR-MCP-013).

## 9. Canonical Request Envelope (Target)

Internal normalization before routing (`AI_PIPELINE.md` §6). Public APIs map into:

| Field | Rule |
|---|---|
| `request_id` | Correlation for turn + background work |
| `actor_id` | Required before multi-user / non-loopback |
| `memory_scope` | Deterministic from policy |
| `input_modality` | `text` \| `speech` |
| `response_mode` | `text` \| `speech` \| `follow_input` |
| `original_text` / `normalized_text` | Exact vs safe normalize |
| `network_policy` | `deny` \| `explicit_only` \| `allow_if_needed` |
| `memory_policy` | `disabled` \| `short_term_only` \| `enabled` |

## 10. Search / STT / TTS Public Schemas (Target)

**Not Implemented.** Future routes/adapters must:

- wrap the same text-first pipeline;
- expose search eligibility/failure states distinctly from no-result;
- accept audio with byte/duration/format limits for STT;
- return text always when TTS is requested; audio is additive (`VOICE_PIPELINE.md`).

Do not claim these endpoints exist until adapters and tests ship.

## 11. Error Shape (Target)

Stable fields: `code`, safe `message`, HTTP status, `request_id`, `retryable`, optional remediation. Taxonomy categories: validation, configuration, authentication/policy, provider, memory, media, tool, system (PRD §14.2). Detail in `docs/engineering/ERROR_HANDLING.md`.

**Implemented today:** many paths use `{"error": "..."}` via `json_error`; middleware 500 includes `request_id`.

## 12. Auth Note

API-007 / SEC-004: administrative, memory, and tool routes are unsafe to expose beyond loopback without an authenticated deployment profile. No client auth Implemented.

## 13. Related Documents

- `docs/architecture/SYSTEM_DESIGN.md`
- `docs/architecture/VOICE_PIPELINE.md`
- `docs/engineering/ERROR_HANDLING.md`
- `docs/requirements/FUNCTIONAL_REQUIREMENTS.md`
