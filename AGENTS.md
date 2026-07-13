# Agent Operating Guide

This file is the working contract for AI agents and human contributors changing this repository. Follow it before editing code, docs, configuration, tests, or operational scripts.

## Project Identity

This repository implements the **Hybrid AI Gateway**: a local FastAPI control plane that exposes OpenAI-compatible chat/image APIs, routes requests to configured hosted NVIDIA models, adds scoped local memory, exposes MCP-style local tools with approvals, and provides health/metrics endpoints.

The product is **hybrid**, not fully local. Gateway control, routing, memory records, vector indexes, tool policy, approvals, and observability run locally. Model inference, embeddings, vision analysis, image generation, and image editing currently use hosted NVIDIA APIs.

Primary references:

- `docs/PRD.md`: product direction, scope, roadmap, requirements, and acceptance strategy.
- `docs/ARCHITECTURE.md`: subsystem ownership, request flows, data/storage model, lifecycle, gaps, and target architecture.
- `README.md`: current setup, endpoints, environment variables, and operational notes.

If these documents disagree with implementation, inspect the code and report the mismatch. Do not silently rewrite product or architecture intent while making an unrelated change.

## Repository Map

| Area | Path | Purpose |
|---|---|---|
| FastAPI app and lifecycle | `gateway/main.py` | App construction, middleware, startup/shutdown, router registration. |
| Chat API | `gateway/routers/chat_router.py`, `gateway/controllers/chat_controller.py` | `/v1/chat/completions` and `/chat` behavior. |
| Hosted provider calls | `agent/llm.py` | NVIDIA-compatible chat, streaming, image generation, and image editing calls. |
| Routing | `router/model_router.py`, `router/intent_router.py`, `router/tool_router.py` | Model selection, intent routing, and legacy keyword tool behavior. |
| Memory facade/services | `memory/` | Memory storage, retrieval, embeddings, vector indexes, short-term traces, long-term facts. |
| Memory background work | `memory/pipelines/memory_pipeline.py`, `gateway/rq_worker.py`, `gateway/memory_jobs.py` | In-process or Redis/RQ memory queue. |
| MCP/tools/approvals | `gateway/routers/mcp_router.py`, `gateway/controllers/tool_controller.py`, `tools/`, `permissions/` | Tool discovery, approval flow, policy, execution. |
| Multimodal handling | `gateway/services/multimodal_materializer.py` | Image/video URL materialization and frame extraction. |
| Health/metrics | `gateway/routers/health_router.py`, `gateway/routers/metrics_router.py`, `gateway/telemetry.py` | Readiness, liveness, route manifest, Prometheus metrics. |
| Tests | `tests/` | Unit and FastAPI tests for memory, routing, health, metrics, multimodal, and gateway flows. |

## Working Rules

1. Inspect before editing. Read the relevant flow end to end, including routes, controllers, services, repositories, config, tests, and docs.
2. Prefer existing patterns over new abstractions. Reuse local helpers, services, repository mixins, and response conventions where they already fit.
3. Keep changes scoped. Do not refactor unrelated modules, rename public routes, or change product claims unless the task requires it.
4. Preserve compatibility by default. `/v1/chat/completions`, `/chat`, `/v1/models`, `/memory/*`, `/mcp/*`, `/health/*`, and `/metrics` are active integration surfaces.
5. Treat docs as product contracts. If implementation is prototype-grade, label it as a gap instead of describing it as production complete.
6. Never claim a check passed unless you ran it successfully.

## Security And Trust Boundaries

Be conservative around these areas:

- **Authentication:** the gateway currently does not provide a completed client authentication/authorization boundary. Do not imply shared or network-exposed deployment is safe.
- **Provider egress:** prompts, selected memory context, media, extracted frames, and embedding text may be sent to hosted NVIDIA APIs.
- **Memory scopes:** scopes are application-level selectors today, not authenticated tenant boundaries.
- **Approvals:** approvals are process-local and not yet actor-bound, expiring, or durable.
- **Tools:** file writes/deletes and shell commands require approval. Shell execution uses guardrails but is not a production sandbox.
- **Multimodal fetching:** broad URL and local file handling exists. SSRF, DNS rebinding, redirect escape, trusted roots, and malicious media handling are not production-hardened.
- **Secrets:** never log or commit provider keys, tokens, `.env` contents, credentials, raw approval IDs in metrics labels, or sensitive user data.
- **Derived data:** vector indexes, memory databases, logs, and runtime artifacts can contain user data. Do not treat them as source files.

When making security-sensitive changes, explicitly check for information leakage, path traversal, command injection, approval bypass, scope leakage, SSRF, secret exposure, and unsafe logging.

## Implementation Guidance

### Chat And Provider Changes

- Trace from `gateway/routers/chat_router.py` into `gateway/controllers/chat_controller.py`, then into routing, multimodal materialization, memory retrieval, and `agent/llm.py`.
- Keep provider-specific behavior isolated. New provider behavior should move toward an adapter boundary rather than adding scattered conditionals.
- Preserve streaming and non-streaming response shapes unless intentionally changing the API contract.
- Do not route image or video requests to text-only models.

### Memory Changes

- Treat relational records as authoritative and FAISS/pgvector indexes as derived.
- Preserve explicit `memory_scope` resolution before reads and writes.
- Keep chat fast path separate from routine memory writes when safe.
- Be careful with the transitional memory architecture: facade, legacy service methods, short-term traces, long-term facts, profile facts, and vector stores coexist.
- Deletion/reindex behavior must keep relational and derived retrieval semantics aligned.

### MCP And Tool Changes

- Tool policy must be deterministic and independent of model persuasion.
- Approval-required tools must not execute until approval is granted and consumed.
- File tool paths must remain under the approved root after resolution.
- Shell behavior must remain bounded by working directory, timeout, output limits, and deny policy. Strengthening is welcome; broadening requires explicit justification.
- Cursor bridge changes must preserve gateway approval semantics and must not become an alternate authorization path.

### Multimodal Changes

- Enforce byte, frame, timeout, and cleanup limits.
- Treat all fetched content and metadata as untrusted.
- Do not weaken URL, file, redirect, MIME, or subprocess safeguards.
- If adding local file support, keep it behind explicit trusted roots and canonical path checks.

### Documentation Changes

- Use `Implemented`, `Target`, and `Gap` language when documenting architecture or requirements.
- Keep `docs/ARCHITECTURE.md` technical and flow-oriented.
- Keep `docs/PRD.md` product/outcome-oriented.
- Put detailed API, security, memory/RAG, deployment, and testing contracts in their companion docs rather than duplicating the full PRD everywhere.

## Verification

Use the smallest meaningful verification set for the change, then broaden when the touched surface is shared or security-sensitive.

Typical commands:

```bash
python3 -m pytest tests/test_health_endpoints.py tests/test_metrics_endpoint.py
python3 -m pytest tests/test_gateway_memory_flow.py tests/test_memory_service.py
python3 -m pytest tests/test_multimodal_materializer.py
python3 -m pytest
```

If the environment lacks dependencies, report the exact command and failure. In this workspace, `python` may be unavailable and `pytest` may need installation through the project environment.

For documentation-only changes, at minimum:

```bash
rg --files
rg -n "referenced/path/or/symbol" docs/
git diff -- docs/
```

Before finishing any implementation task, review:

- `git diff`
- changed public routes and response shapes
- configuration/environment variable impact
- security/trust-boundary implications
- tests added or updated for meaningful behavior
- docs that need to reflect the change

## Current Known Gaps

These are known and should not be accidentally described as complete:

- Loopback-first deployment is a PRD target, but `start.sh` currently binds Uvicorn to `0.0.0.0`.
- Client authentication and authorization are not production-complete.
- Public request/response models still use loose dictionaries in several routes.
- Approval storage is in-memory and lacks durable audit, actor binding, expiry, and race/replay hardening.
- Rate limiting and metrics are process-local.
- Memory has legacy and newer paths that need consolidation and migration planning.
- Runtime schema setup is not a replacement for production migrations.
- Media fetching and local file handling need production SSRF and trusted-root controls.
- Companion docs under `docs/architecture/`, `docs/requirements/`, `docs/engineering/`, and `docs/operations/` may still be placeholders.

## Definition Of Done

A task is done when:

- The relevant flow was inspected before editing.
- Changes are scoped to the requested behavior.
- Existing public contracts are preserved or intentionally documented as changed.
- Security and privacy implications were considered.
- Tests or appropriate verification commands were run, or the inability to run them is explained.
- Documentation is updated when behavior, setup, architecture, or requirements change.
- The final response states what changed, what was verified, and any genuine remaining risk.
