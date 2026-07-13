# Hybrid AI Gateway Architecture

Version: 1.0  
Baseline: commit `9fadfd7`  
Status: architecture baseline for the current implementation and PRD-aligned target direction

## 1. Overview

The Hybrid AI Gateway is a locally operated FastAPI control plane for AI clients. It exposes OpenAI-compatible chat and image endpoints, routes requests to configured hosted models, applies the canonical AI pipeline, adds scoped local memory, exposes local tools through MCP-style endpoints, and records basic operational evidence.

The product is hybrid by design. The gateway, routing, memory records, vector indexes, tool policy, approvals, and observability run locally. Model inference, embeddings, vision analysis, image generation, and image editing currently use NVIDIA-hosted APIs configured through environment variables.

`docs/architecture/AI_PIPELINE.md` is the source of truth for input normalization, exact short-term capture, normalized long-term extraction, retrieval order, evidence sufficiency, internet-search fallback, and response modality. This document describes where that pipeline fits in the broader system.

Architecture labels used in this document:

| Label | Meaning |
|---|---|
| Implemented | Present in the inspected repository. |
| Target | Intended production direction from the PRD. |
| Gap | Known risk, transitional implementation, or missing hardening. |

## 2. Architectural Goals

- Provide one local gateway URL for Open WebUI, direct API clients, and Cursor MCP integration.
- Keep model selection, memory scope resolution, tool permissions, and approvals under deterministic local code.
- Route every text request through the canonical AI pipeline before model response generation.
- Preserve OpenAI-compatible behavior where explicitly supported, while documenting gateway-specific extensions.
- Keep chat response latency independent from routine memory writes where safe.
- Treat exact short-term traces and normalized long-term facts as authoritative relational data, and vector indexes as rebuildable derived state.
- Search scoped local memory and determine evidence sufficiency before any future internet-search fallback.
- Make provider, media, memory, and tool boundaries visible enough for engineering, security, and operations review.
- Avoid claiming fully local inference, enterprise multi-tenancy, production authentication, implemented STT/TTS, implemented internet search, or hardened SSRF protection until those are implemented and verified.

## 3. Runtime Topology

```text
Open WebUI / Direct API clients
        |
        | HTTP, OpenAI-compatible subset
        v
FastAPI Gateway: gateway/main.py
        |
        +--> Chat routes: /v1/chat/completions, /chat
        |       |
        |       +--> AI pipeline: input normalization, evidence, response modality
        |       +--> Routing: router/model_router.py, router/intent_router.py
        |       +--> Provider client: agent/llm.py
        |       +--> NVIDIA hosted chat/vision endpoints
        |       +--> Local memory retrieval + exact/normalized memory writes
        |
        +--> Image routes: /v1/images/generations, /v1/images/edits
        |       |
        |       +--> agent/llm.py
        |       +--> NVIDIA hosted image endpoints
        |
        +--> Memory routes: /memory/*
        |       |
        |       +--> memory.facade.MemoryFacade
        |       +--> memory.service.MemoryService
        |       +--> SQLAlchemy records + FAISS or pgvector
        |
        +--> MCP routes: /mcp/*
        |       |
        |       +--> permissions.policy
        |       +--> permissions.approvals
        |       +--> tools.registry
        |       +--> file_tools / shell_command
        |
        +--> Health and metrics: /health/*, /metrics

Cursor MCP client
        |
        | FastMCP bridge
        v
cursor_mcp_server.py
        |
        v
Gateway /mcp/* endpoints
```

Implemented: `start.sh` starts the FastAPI gateway with Uvicorn and launches Open WebUI in Docker, configured to call the gateway at `/v1`. Cursor integration is provided by `cursor_mcp_server.py`, which forwards MCP tool calls to the gateway HTTP API.

Gap: `start.sh` currently binds Uvicorn to `0.0.0.0`. The PRD target is loopback-first by default unless a secured deployment profile is explicitly configured.

## 4. Core Subsystems

| Subsystem | Implemented owner | Responsibility |
|---|---|---|
| Application lifecycle | `gateway/main.py` | FastAPI app construction, router inclusion, startup/shutdown, request IDs, timing headers, top-level error handling. |
| Chat API | `gateway/routers/chat_router.py`, `gateway/controllers/chat_controller.py` | OpenAI-style chat endpoint handling, streaming/non-streaming behavior, model routing, memory context, multimodal handling, retries and fallbacks. |
| AI pipeline contract | `docs/architecture/AI_PIPELINE.md` | Source of truth for input normalization, exact short-term capture, normalized long-term extraction, retrieval order, evidence sufficiency, internet fallback, and response modality. |
| Provider client | `agent/llm.py` | NVIDIA-compatible chat, streaming, image generation, image editing, timeout handling, upstream error markers, async HTTP client lifecycle. |
| Model and intent routing | `router/model_router.py`, `router/intent_router.py`, `router/tool_router.py` | Deterministic model selection for vision, code, Bangla, and default requests; optional intent routing, internet-search intent labeling, and legacy keyword tools. |
| Memory facade | `memory/facade.py` | Gateway-facing entry point for short-term memory, long-term memory, retrieval, extraction, and legacy compatibility methods. |
| Memory service and storage | `memory/service.py`, `memory/repository.py`, `memory/repositories/*`, `memory/vector_store.py`, `memory/pgvector_store.py` | SQLite/SQLAlchemy records, exact short-term traces, normalized long-term facts, legacy memory records, embeddings, FAISS/pgvector retrieval, reindex and deletion. |
| Background memory pipeline | `memory/pipelines/memory_pipeline.py`, `gateway/memory_jobs.py`, `gateway/rq_worker.py` | Asynchronous user/assistant turn storage through in-process queue or Redis/RQ backend. |
| MCP and tools | `gateway/routers/mcp_router.py`, `gateway/controllers/tool_controller.py`, `tools/`, `permissions/` | Tool discovery, tool execution, policy decision, approval creation/consumption, file and shell tool execution. |
| Multimodal materialization | `gateway/services/multimodal_materializer.py` | Image/video URL normalization, data URL conversion, video frame extraction, YouTube fallback behavior, multimodal HTTP client cleanup. |
| Health, metrics, telemetry | `gateway/routers/health_router.py`, `gateway/routers/metrics_router.py`, `gateway/telemetry.py`, `gateway/memory_metrics.py` | Liveness/readiness, route manifest checks, Prometheus text metrics, request counters/latency, memory diagnostics. |
| Configuration | `config.py` | Environment-driven model IDs, provider endpoints, memory settings, queue settings, limits, timeouts, logging, routing flags, and feature toggles. |

Target: public trust-boundary inputs should move from loose dictionaries toward typed request and response schemas. Provider-specific logic should remain behind a clear adapter boundary rather than spreading through controllers.

## 5. Request Flows

### 5.1 Chat Completion Flow

```text
Client
  -> POST /v1/chat/completions or /chat
  -> chat_router.chat_completions
  -> chat_controller.handle_chat_completions
  -> parse request and rate-limit client IP
  -> normalize input and resolve memory scope
  -> materialize/promote multimodal inputs if present
  -> retrieve scoped local short-term/long-term evidence
  -> decide whether local evidence is sufficient
  -> choose upstream model
  -> call agent.llm complete or stream path
  -> return OpenAI-style response or SSE stream
  -> capture exact short-term turn and enqueue long-term extraction when eligible
```

Implemented:

- `/v1/chat/completions` and `/chat` share the same controller.
- Text, image, and video-like inputs are handled before provider execution.
- Routing can select vision, code, Bangla, or default models from configuration.
- Memory context may be injected into the prompt when `MEMORY_ENABLED` is true.
- User and assistant turns can be captured for exact short-term memory and queued for long-term extraction after the response path.

Gap:

- Request validation is still controller/helper driven and uses untyped payloads at public boundaries.
- Client API keys are not currently treated as an authentication boundary.
- Some fallback and humanization behavior is implemented in controller logic rather than a small provider/runtime policy layer.
- Formal evidence bundles, evidence sufficiency decisions, STT/TTS response modality, and internet-search fallback are target pipeline features, not complete implementation.

### 5.2 Streaming Chat Flow

```text
Client
  -> stream=true
  -> gateway StreamingResponse
  -> agent.llm.stream(...)
  -> NVIDIA SSE stream
  -> gateway parses upstream data lines
  -> gateway emits OpenAI-style chunks
  -> data: [DONE]
```

Implemented:

- Text streaming uses upstream streaming where possible.
- Vision requests are sent through a non-stream upstream call for reliability, then returned to the client through the gateway response path.
- Upstream network errors and LLM errors are converted into gateway-visible failure content or JSON errors depending on the path.

Target:

- Streaming protocol behavior should be documented in `docs/architecture/API_DESIGN.md`, including terminal events, cancellation, error termination, and heartbeat/status behavior.

### 5.3 Multimodal Chat Flow

```text
User message with image_url/video_url/text URL
  -> gateway.services.multimodal_materializer
  -> fetch file/http/data URL or resolve YouTube/video input
  -> enforce configured byte/frame limits
  -> convert images or extracted frames to data URLs
  -> route to configured vision model
  -> call provider
```

Implemented:

- The materializer supports data URLs, `http`/`https`, `file://`, video frame extraction through FFmpeg, and YouTube handling through `yt-dlp` where available.
- `MAX_VISION_IMAGE_BYTES`, `MAX_VISION_VIDEO_BYTES`, `VISION_VIDEO_MAX_FRAMES`, and related settings constrain processing.
- Generic vision refusals can be rewritten into clearer diagnostics.

Gap:

- Private network destinations, local files, redirects, and SSRF controls are not yet production-hardened.
- Trusted local file access needs explicit approved roots and canonical path enforcement before non-loopback or shared use.

### 5.4 AI Pipeline And Memory Flow

```text
Accepted text request
  -> normalize text and resolve memory_scope
  -> search scoped short-term exact/contextual memory
  -> search scoped long-term structured facts
  -> search scoped vector/FTS/lexical memory
  -> rank/filter evidence and inject bounded context
  -> generate text response
  -> store exact user/assistant turn in short-term trace
  -> queue long-term extraction
  -> classify importance/category/confidence
  -> reject low-value/noisy/unsafe content
  -> store normalized durable facts
  -> update derived embedding and FAISS/pgvector indexes
```

Implemented:

- Memory APIs support add, store alias, search, list, stats, short traces, delete, and reindex.
- SQLite/SQLAlchemy is the default durable store.
- FAISS is the default local vector backend; pgvector is available as a production-oriented backend with fallback to FAISS if initialization fails.
- Short-term traces and runtime memory metrics are stored through repository mixins.
- The memory facade bridges newer services and legacy `memory_service` behavior.
- `router/intent_router.py` can label `internet_search`, but there is no implemented web-search executor.

Gap:

- The memory architecture is transitional: legacy records, newer long-term services, profile facts, short traces, and vector indexes coexist.
- Short-term retention currently has a conflicting default: `SHORT_TERM_RETENTION_HOURS=24`, while `SHORT_TERM_CLEAR_ON_RESTART=true` clears short-term tables on restart.
- Evidence sufficiency, evidence bundles, policy-gated internet search, and STT/TTS response modality are target behavior defined in `docs/architecture/AI_PIPELINE.md`.
- Runtime `create_all`-style schema setup is not a production migration strategy.
- Derived indexes under local files may contain user data and should not be committed or treated as source.

### 5.5 MCP Tool Approval and Execution Flow

```text
Client or Cursor bridge
  -> POST /mcp/execute
  -> validate tool name and arguments object
  -> permissions.policy.evaluate_tool_action
  -> if approval required:
        create PendingApproval in process memory
        return approval_id
  -> POST /mcp/approve with decision
  -> client retries /mcp/execute with approval_id
  -> approval_store.consume_if_valid
  -> tools.registry.run_tool
  -> return structured result
```

Implemented:

- Tool discovery is available through `/mcp/tools`.
- File writes/deletes and shell commands require approval.
- Approval consumption checks tool name and an argument hash and prevents reuse after consumption.
- `file_tools` restricts file operations to the repository `files/` directory.
- `shell_command` restricts working directory to the repository tree, applies a denylist, captures output, and enforces a timeout.
- `cursor_mcp_server.py` preserves gateway approval flow by forwarding execute, list approvals, and approval decision calls.

Gap:

- Approval state is in process memory and is not durable across restarts.
- Approval records are not actor-bound, expiring, or tied to authenticated client identity.
- `shell_command` uses `shell=True`; the denylist is a guardrail, not a complete command policy.

### 5.6 Image Generation and Editing Flow

```text
Client
  -> POST /v1/images/generations or /v1/images/edits
  -> image router rate-limit and parse JSON
  -> agent.llm.generate_image or edit_image
  -> NVIDIA image endpoint
  -> return upstream JSON or normalized error
```

Implemented:

- Image generation and editing have OpenAI-style routes.
- Missing or unavailable provider/model combinations return clearer gateway errors for known 404 cases.
- Outputs are proxied from the hosted provider and are not intentionally persisted by the gateway route.

Target:

- Image request/response schemas, limits, model capability metadata, and provider correlation metadata should be documented in the API design companion document.

## 6. Data and Storage Model

| Data | Implemented storage | Authority | Notes |
|---|---|---|---|
| Memory records | SQLite through SQLAlchemy by default | Authoritative | `MemoryRecord` stores scope, text, source, category, structured data, importance, confidence, and timestamp. |
| Exact short-term traces | SQLite through SQLAlchemy | Authoritative for recent exact turn history | Short-term rows preserve accepted user wording and final assistant text, bounded by TTL/count policy. |
| Long-term/profile facts | Repository/service methods under `memory/` | Transitional authoritative data | Used by normalized profile and structured fact behavior; architecture is still consolidating. |
| Vector index | FAISS files or pgvector | Derived | Rebuilt through `/memory/reindex`; must match embedding model and dimension. |
| Embeddings | NVIDIA embedding endpoint through `NvidiaEmbeddingService` | Derived from text | Hosted embedding calls mean eligible memory text can cross the provider boundary. |
| Future evidence bundle | Target contract in `AI_PIPELINE.md` | Request-scoped reference data | Separates conversation context, short-term memory, long-term memory, internet sources, model knowledge, and tool results. |
| Approval records | In-memory `ApprovalStore` | Runtime-only | Lost on restart; suitable for local prototype flow, not production governance. |
| Tool files | Repository `files/` directory | Local tool state | File tool operations are rooted here. |
| Open WebUI state | Docker volumes from `start.sh` | External client state | Owned by the Open WebUI container, not by gateway storage APIs. |
| Logs and metrics | Process logs and in-memory telemetry | Operational evidence | Metrics are exposed as Prometheus text at `/metrics`; logs may be JSON when configured. |

Target:

- Database changes should use versioned migrations.
- Backups should cover relational memory, configuration, approvals/audit when applicable, and Open WebUI volumes.
- Vector indexes should remain rebuildable from authoritative records.
- Production short-term defaults should retain unexpired rows across ordinary restart; `SHORT_TERM_CLEAR_ON_RESTART=true` should remain a development/test option.
- Development/test data should avoid real personal data.

## 7. Configuration and Lifecycle

Configuration is centralized in `config.py` and read primarily from environment variables loaded from `.env`.

Major configuration groups:

- Provider and model IDs: `DEFAULT_MODEL`, `BANGLA_MODEL`, `CODE_MODEL`, `VISION_MODEL`, `VISION_FALLBACK_MODELS`, `IMAGE_GEN_MODEL`, `IMAGE_EDIT_MODEL`.
- Provider endpoints and credentials: `NVIDIA_API_KEY`, `BASE_URL`, `EMBEDDING_BASE_URL`, `IMAGE_BASE_URL`, `IMAGE_EDIT_BASE_URL`.
- Memory: `MEMORY_ENABLED`, `MEMORY_SQLITE_URL`, `MEMORY_VECTOR_PATH`, `MEMORY_VECTOR_BACKEND`, `MEMORY_TOP_K`, `MEMORY_MIN_SCORE`, retention and queue settings.
- AI pipeline target settings: response modality, STT/TTS enablement, internet-search enablement, search mode, evidence sufficiency, and long-term classifier thresholds are defined by `AI_PIPELINE.md` but are not all implemented in `config.py` today.
- Multimodal: image/video byte limits, frame limits, frame interval, YouTube cookie profile.
- Runtime controls: rate limits, stream timeouts, retries, debug/step logs, response validation retry, humanization, shadow monitoring.

Lifecycle:

```text
Import config and singleton clients
  -> construct FastAPI app
  -> configure debug/step logging
  -> startup: start memory pipeline
  -> serve requests
  -> shutdown: stop memory pipeline, close LLM client, close multimodal HTTP client, close memory service
```

Implemented:

- Readiness checks validate `NVIDIA_API_KEY`, memory access when enabled, and expected route registration.
- Shutdown attempts to close the memory pipeline, provider HTTP client, multimodal HTTP client, and memory service.
- Request middleware attaches `X-Request-Id` and `X-Process-Time-Ms`.

Gap:

- Startup validation is not yet a full typed configuration validation phase.
- Optional binary dependency status such as FFmpeg and `yt-dlp` is not reported as a capability matrix.

## 8. Security and Trust Boundaries

### 8.1 Local Gateway Boundary

Implemented: the gateway exposes local HTTP APIs and Open WebUI integration.  
Gap: client API keys are not a completed authentication boundary. Non-loopback exposure should be treated as unsafe until an authenticated deployment profile exists.

### 8.2 Hosted Provider Boundary

Implemented: chat, embeddings, vision, image generation, and image editing use NVIDIA-hosted APIs.  
Security implication: prompts, selected memory context, media, extracted frames, and embedding text may leave the local machine.  
Target: provider egress must be documented and minimized, and provider-specific behavior should be isolated behind adapter contracts.

### 8.3 Memory Scope Boundary

Implemented: memory APIs and chat flow resolve a `memory_scope` before reads and writes.  
Gap: scope is not yet bound to authenticated identity. Cross-scope fallback exists in selected memory paths and must not become an identity bypass. Any future shared deployment must add authentication and authorization before relying on scopes as a security boundary.

### 8.4 AI Pipeline Evidence Boundary

Implemented: selected memory can be injected into provider prompts as context.  
Target: evidence bundles must separate current conversation, exact short-term memory, normalized long-term memory, internet sources, model background knowledge, and tool results. Evidence and web/search content are untrusted reference data, not policy instructions.  
Gap: formal evidence bundles, evidence sufficiency decisions, cited internet evidence, and no-result states are not complete implementation.

### 8.5 Tool Execution Boundary

Implemented: tool execution goes through deterministic policy and approval checks; file and shell tools have local restrictions.  
Gap: approvals are in-memory and not actor-bound or expiring. Shell execution still needs a stricter command policy for production use.

### 8.6 Media Fetch Boundary

Implemented: media materialization fetches data URLs, local files, HTTP(S) URLs, and video sources with configured size/frame limits.  
Gap: SSRF, DNS rebinding, redirect escape, local file policy, malicious media, and subprocess sandboxing require hardening before untrusted or network-exposed use.

### 8.7 Voice And Internet Fallback Boundary

Implemented: text chat is the current input/output path, and `internet_search` exists only as an intent label.  
Target: future STT/TTS adapters must wrap the same text-first AI pipeline, and future internet search must run only after local evidence is insufficient and policy permits external lookup.  
Gap: there is no STT service, TTS engine, audio route, search-provider adapter, or production internet-search executor today.

## 9. Observability and Operations

Implemented:

- `/health/live` reports process liveness.
- `/health/ready` checks provider credential presence, memory availability, expected routes, and memory queue depth.
- `/health/routes` reports registered routes and missing expected endpoints.
- `/metrics` exposes Prometheus text metrics from `gateway.telemetry`.
- Request middleware records request count and latency and returns request correlation headers.
- JSON request logs can be enabled with `LOG_JSON`.
- Memory observability is exposed through `/memory/stats`, including short-term trace counts and memory filter snapshots.

Target:

- Metrics labels should remain bounded and avoid prompts, raw URLs, memory text, approval IDs, and request IDs.
- Release profiles should define log rotation, retention, redaction, and debug/step logging policy.
- Provider latency, gateway latency, queue failures, media failures, approval states, evidence sufficiency, search fallback decisions, STT/TTS outcomes, and memory quality metrics should be measured separately.

## 10. Known Architectural Gaps

These gaps are intentionally documented so future implementation does not mistake prototype behavior for production guarantees.

- No completed authentication or authorization boundary for gateway clients.
- Uvicorn startup script binds to `0.0.0.0`, while the PRD target is loopback-first by default.
- Approval storage is process-local and lacks actor binding, expiry, durable audit, and replay/race hardening.
- Rate limiting and metrics are process-local.
- Public request/response models are not consistently typed at API boundaries.
- No canonical request envelope, response-mode contract, or formal evidence bundle is implemented yet.
- STT/TTS and internet-search execution are target capabilities only.
- Evidence sufficiency and no-reliable-information states are not complete implementation.
- Media fetching allows broad URL and file inputs without production-grade SSRF controls.
- Memory architecture contains legacy and newer paths that need consolidation and migration planning.
- Short-term memory currently has a production-target conflict: default TTL is 24 hours, but restart clearing is enabled by default.
- Runtime schema creation is not a production migration strategy.
- Provider-specific NVIDIA behavior is still visible in general provider/client modules.
- Companion docs for API design, memory/RAG, security, deployment, testing, and operations are still placeholders or separate work.

## 11. Target Architecture Direction

The PRD-aligned production MVP should evolve toward:

- Loopback-first local deployment by default.
- Explicit authenticated profile before any non-loopback or shared deployment.
- A provider adapter boundary with NVIDIA as the first supported provider.
- Gateway model aliases and capability metadata separated from provider model IDs.
- Canonical AI pipeline contract from `docs/architecture/AI_PIPELINE.md`: text-first input normalization, exact short-term capture, normalized long-term extraction, local evidence first, evidence sufficiency, and response modality.
- Typed public API schemas and documented OpenAI-compatible subset.
- Versioned database migrations and clear backup/restore procedures.
- Consolidated memory architecture with exact short-term traces, normalized long-term facts, authoritative relational records, and rebuildable vector indexes.
- Policy-gated internet-search adapter only after local memory is insufficient and external lookup is allowed.
- Future STT/TTS adapters that preserve the text answer and do not bypass the AI pipeline.
- Hardened media policy that denies private/local destinations by default and allows local files only through trusted roots.
- Durable, actor-bound, argument-bound, expiring, one-time approvals.
- Bounded tool execution with stricter shell command policy, output limits, sanitized environment, and audit evidence.
- Reproducible deployment documentation for local workstation, development, and future team/internal profiles.

## 12. Companion Documents

This architecture document is the high-level system architecture source of truth. Detailed pipeline, API, memory, security, deployment, and testing contracts should live in companion documents:

- `docs/PRD.md`: product scope, outcomes, requirements, roadmap, and acceptance strategy.
- `docs/architecture/AI_PIPELINE.md`: source of truth for input normalization, memory lanes, evidence sufficiency, internet fallback, and response modality.
- `docs/architecture/API_DESIGN.md`: route contracts, schemas, streaming protocol, errors, and compatibility notes.
- `docs/architecture/MEMORY_AND_RAG.md`: memory taxonomy, ranking, extraction, queue semantics, migrations, and evaluation.
- `docs/architecture/VOICE_PIPELINE.md`: future STT/TTS input and output contracts.
- `docs/requirements/SECURITY_REQUIREMENTS.md`: threat model, trust boundaries, egress, auth, SSRF, tool risks, and secret handling.
- `docs/operations/DEPLOYMENT.md`: local setup, network profiles, storage, backups, Open WebUI, and upgrades.
- `docs/engineering/TESTING_STRATEGY.md`: unit, integration, contract, security, performance, and operational tests.

Until those companion documents are complete, this file and `README.md` are the primary implementation-oriented references, with `docs/PRD.md` providing the product direction.
