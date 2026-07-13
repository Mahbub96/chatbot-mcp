# Hybrid AI Gateway — System Design (Routing and Providers)

Version: 1.0

Last reviewed: 13 July 2026

Status: companion to system and product authorities; labels Implemented / Target / Gap against repository evidence

## 1. Purpose

This document owns **model selection, gateway aliases, capability metadata, retries, and fallbacks**.

Authorities:

| Topic | Source of truth |
|---|---|
| System topology and trust boundaries | `docs/ARCHITECTURE.md` |
| AI pipeline (memory, evidence, modality) | `docs/architecture/AI_PIPELINE.md` |
| Product requirements | `docs/PRD.md` §8 |
| Observed code behavior | `router/model_router.py`, `router/intent_router.py`, `agent/llm.py`, `config.py` |

## 2. Scope Boundary

In scope here: deterministic routing, provider adapter expectations, aliases vs provider IDs, modality-preserving fallback.

Out of scope: full request topology (`ARCHITECTURE.md`), memory/RAG detail (`MEMORY_AND_RAG.md`), public schemas (`API_DESIGN.md`), STT/TTS (`VOICE_PIPELINE.md`).

## 3. Implemented Routing Behavior

**Implemented** in `router/model_router.pick_upstream_model()`:

1. If `VISION_MODEL` is set and messages contain an `image_url` part → vision model.
2. Else if `CODE_MODEL` is set and latest user text matches code markers → code model.
3. Else if `BANGLA_MODEL` is set and text contains Bangla Unicode → Bangla model.
4. Else → `DEFAULT_MODEL`.

Detectors: `has_image`, `contains_code_intent`, `contains_bangla_text`. Routing is side-effect free and returns a provider model string.

**Gap:** Client-facing gateway aliases are not yet a stable public contract. `GET /v1/models` currently exposes a simplified local listing rather than a full capability matrix (see `API_DESIGN.md`).

## 4. Target Routing Precedence

From PRD §8.2 (Target):

1. Explicitly supported client model alias (when policy allows selection).
2. Multimodal / vision requirement.
3. Code-specialized intent.
4. Bangla-language intent.
5. Default text model.

Modality capability **must** override language or code specialization. Example: Bangla + image → vision-capable route, not Bangla text-only.

| ID | Priority | Requirement | Status |
|---|---|---|---|
| FR-RTE-001 | Must | Deterministic for same normalized request and config | Implemented (heuristic path) |
| FR-RTE-002 | Must | Modality precedes language/code specialization | Implemented for image vs text |
| FR-RTE-003 | Must | LLM intent suggestion advisory only; cannot expand permission/network/modality | Partially: intent labels exist; must stay non-authoritative |
| FR-RTE-004 | Must | Missing specialized config → explicit fallback or config error | Partial: empty vision config can error; other gaps remain |
| FR-RTE-005 | Should | Observable sanitized reason codes and selected alias | Gap |
| FR-RTE-006 | Must | Code/Bangla regression fixtures | Partial suite coverage |
| FR-RTE-007 | Must | Route selection before provider execution; stable unless approved fallback | Implemented for initial pick |

## 5. Provider Boundary

NVIDIA is the **Phase 1** hosted provider (OD-015). Inference, embeddings, vision, image generation, and image editing leave the local machine when hosted APIs are used.

| ID | Priority | Requirement | Status |
|---|---|---|---|
| FR-PRV-001 | Must | Credentials from secret config; never returned in APIs/logs/metrics/memory/tools | Implemented loading; continuous redaction hardening required |
| FR-PRV-002 | Must | Bounded connect/read/write/total/retry budgets by modality | Partial timeouts exist |
| FR-PRV-003 | Must | Retries only for retry-safe failures | Gap: formalize budgets |
| FR-PRV-004 | Must | Fallback preserves modality and capability | Target; vision must never fall to text-only |
| FR-PRV-005 | Must | Disclose provider egress | Target docs (`DEPLOYMENT.md`, this section) |
| FR-PRV-006 | Should | Cached/bounded provider health checks | Gap |
| FR-PRV-007 | Must | Reject malformed “success” provider responses | Partial |

**Target:** isolate provider-specific URLs, headers, retries, and normalization behind an adapter. Controllers must not accumulate provider conditionals.

## 6. Gateway Aliases Versus Provider IDs

| Concept | Rule | Status |
|---|---|---|
| Gateway alias | Stable client-facing ID with capability flags | Target (OD-004) |
| Provider model ID | Upstream NVIDIA (or future) identifier | Implemented via env (`DEFAULT_MODEL`, etc.) |

Clients should not be forced to reconfigure when a provider model ID changes. `GET /v1/models` must list only configured, eligible gateway IDs (FR-MOD-001…004).

## 7. Capability Matrix (Target)

| Capability | Declared on alias | Notes |
|---|---|---|
| Text chat | Required for default routes | Implemented via chat routes |
| Streaming | Optional flag | Implemented for chat |
| Vision / image input | Required when images present | Implemented routing; config Gap if unset |
| Image generation | Separate route/model | Implemented proxy |
| Image editing | Separate route/model | Implemented proxy |
| Code specialization | Preference, not modality override | Implemented heuristic |
| Bangla specialization | Preference, not modality override | Implemented heuristic |
| Speech STT/TTS | Future | Gap — see `VOICE_PIPELINE.md` |

## 8. Intent Router Role

`router/intent_router.py` may label intents (including `internet_search`).

**Rules:**

- Intent is **advisory** for retrieval staging and future search eligibility.
- Intent must **not** grant tool permission, network access, or change memory scope.
- `internet_search` is a **placeholder** today: no production search executor exists (`AI_PIPELINE.md` §10). Status: Gap / Target (OD-017).

## 9. Retry and Fallback Policy (Target)

- Retry only idempotent or explicitly safe failures (timeouts, selected 5xx).
- Do not retry invalid credentials or validation errors.
- Compatible fallback must preserve modality (FR-PRV-004).
- Missing `VISION_MODEL` with image input → configuration error, not silent text fallback (aligned with current chat controller behavior).

## 10. Observability

**Target (FR-RTE-005):** emit sanitized reason codes such as `vision_required`, `code_intent`, `bangla_intent`, `default`, `client_alias`, without chain-of-thought or raw prompts.

**Implemented:** request IDs and path metrics exist; routing reason codes are not a complete contract yet.

## 11. Evaluation

Routing precision target (PRD success metrics): repeatable fixtures for vision, code, Bangla, mixed language, and code-fence cases at the approved threshold (target ≥95% on labeled fixtures).

## 12. Related Documents

- `docs/ARCHITECTURE.md` — runtime topology
- `docs/architecture/AI_PIPELINE.md` — canonical pipeline
- `docs/architecture/API_DESIGN.md` — public model and chat contracts
- `docs/requirements/FUNCTIONAL_REQUIREMENTS.md` — FR-PRV / FR-RTE / FR-MOD catalogs
