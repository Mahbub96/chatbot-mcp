# Hybrid AI Gateway — Testing Strategy

Version: 1.0

Last reviewed: 13 July 2026

Status: required layers from PRD §18.1 mapped to current `tests/` suite and known Gaps

## 1. Purpose

Define what must be tested, how acceptance evidence is produced, and where the suite is incomplete.

Authorities: PRD §18; `ACCEPTANCE_CRITERIA.md`; AI-PIPE table; AGENTS.md verification notes.

## 2. Required Test Layers

| Layer | Required coverage | Current status |
|---|---|---|
| Unit | Routing, intent, schema, scoring, policy, path/URL, approval state, error mapping | Partial |
| Contract | OpenAI subset, SSE, NVIDIA adapter, vector/queue, MCP bridge, images | Gap / Partial |
| Integration | FastAPI + DB/index, provider stub, Redis/RQ, pgvector, tools, WebUI smoke | Partial FastAPI tests |
| End-to-end | Startup, models, chat, cancel, memory lifecycle, approval, sandbox, provider fail, ready | Partial |
| Security | SSRF, traversal, symlink, injection, approval replay, prompt injection, leakage, redaction | Gap |
| Performance | Overhead, first-event, retrieval scale, backpressure, soak, media limits | Gap |
| Recovery | Disk full, corrupt index, DB/Redis loss, interrupted job, timeout, expired key, shutdown | Gap |
| Compatibility | Pinned Open WebUI, Cursor bridge, client examples | Gap |

## 3. Current Suite Map (`tests/`)

| File | Focus |
|---|---|
| `test_health_endpoints.py` | live/ready/503 |
| `test_metrics_endpoint.py` | Prometheus body |
| `test_gateway_memory_flow.py` | Memory HTTP + chat memory |
| `test_memory_service.py` | Memory service |
| `test_memory_logic.py` | Memory logic |
| `test_retrieval_service.py` | Retrieval |
| `test_intent_router.py` | Intent routing |
| `test_chat_personal_fallback.py` | Personal/fallback chat |
| `test_multimodal_materializer.py` | Media materialization |

**Gaps in tree:** dedicated MCP/approval, images, auth, SSRF, streaming contract, performance, recovery suites. CI must become authoritative (PRD §2.3).

## 4. Typical Local Commands

```bash
python3 -m pytest tests/test_health_endpoints.py tests/test_metrics_endpoint.py
python3 -m pytest tests/test_gateway_memory_flow.py tests/test_memory_service.py
python3 -m pytest tests/test_multimodal_materializer.py
python3 -m pytest
```

Never claim a check passed unless executed successfully. Environment may lack deps; report exact failures.

## 5. Acceptance Linkage

- MVP exit: `ACCEPTANCE_CRITERIA.md` §5
- AI-PIPE-001…015: pipeline fixtures (voice/search deferred where noted)
- Memory quality: precision@5, pollution, leakage, duplicates (PRD §9.3)
- Security suite must include SEC adversarial cases before non-loopback claims
- Performance budgets: NFR-PERF-*; reliability: NFR-REL-*

## 6. Definition of Ready Evidence

Tasks using `tasks/TASK_TEMPLATE.md` must list validation commands and expected evidence links (test names, metrics, screenshots only if needed).

## 7. Related Documents

- `docs/requirements/ACCEPTANCE_CRITERIA.md`
- `docs/operations/RELEASE_CHECKLIST.md`
- `AGENTS.md`
