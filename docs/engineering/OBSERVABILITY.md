# Hybrid AI Gateway — Observability

Version: 1.0

Last reviewed: 13 July 2026

Status: OPS requirements plus Implemented health/metrics surfaces

## 1. Purpose

Logs, metrics, health, redaction, retention, and diagnostics for the gateway.

Authorities: PRD §17.1 (OPS-001…010); `AI_PIPELINE.md` §17; `gateway/telemetry.py`, `gateway/routers/health_router.py`.

## 2. Observability Requirements

| ID | Requirement | Status |
|---|---|---|
| OPS-001 | Correlation ID accepted or generated and returned | Partial (request_id middleware) |
| OPS-002 | Structured logs: timestamp, severity, component, event, request ID, route, sanitized alias, outcome, duration | Partial |
| OPS-003 | Metrics: requests/latency, provider outcomes, routing, first-token, memory, queue, tools, media, resources | Partial |
| OPS-004 | Bounded labels; no raw prompts, memory text, URLs, approval IDs, high-cardinality request IDs as labels | Partial risk |
| OPS-005 | Liveness = process; readiness = required deps + named degraded optionals | Implemented endpoints |
| OPS-006 | Debug/step logging off by default in release | Partial (example enables debug) |
| OPS-007 | Log rotation size/time + protected permissions | Gap |
| OPS-008 | Diagnostic versions/capabilities without secrets | Partial (`/health/routes`) |
| OPS-009 | Separate provider vs gateway latency | Gap |
| OPS-010 | Startup/shutdown report incomplete cleanup / index / queue drain | Gap |

## 3. Implemented Surfaces

### 3.1 Health

| Path | Behavior |
|---|---|
| `GET /health/live` | Process liveness |
| `GET /health/ready` | Checks NVIDIA key presence, memory if enabled, expected routes; 503 if not ready; may include queue depth/reasons |
| `GET /health/routes` | Route manifest / missing expected routes |

### 3.2 Metrics (process-local)

Prometheus text at `GET /metrics`:

- `gateway_requests_total`
- `gateway_request_duration_ms_sum`
- `gateway_requests_by_path_total{method,path,status}`

**Gap:** not multi-process/cluster-safe; no histograms/quantiles; path labels can be high-cardinality if unbounded.

### 3.3 Logs

JSON/structured options via `LOG_JSON`; file debug via `DEBUG_LOG_*`. Request IDs on internal errors.

## 4. Target Pipeline Metrics and Events

From `AI_PIPELINE.md` §17 — add when capabilities exist:

- modality/language input counts; STT/TTS latency and failures
- short-term write success/failure; long-term accept/reject reason codes
- retrieval latency and source blend; evidence-sufficiency decisions
- search eligibility/attempts/results/failures
- TTFT and completion; end-to-end turn outcome

Safe event examples: `input.accepted`, `short_term.user_stored`, `retrieval.completed`, `evidence.insufficient`, `response.started`.

**Never** put raw user text, memory facts, search queries, sensitive URLs, or credentials in metrics or default logs.

## 5. Redaction and Retention

- SEC-011 / PRI-004/005: redact secrets; minimize user content; support bundles default redacted.
- Document retention for logs, traces, retrieval logs, approvals (PRI-006).
- Release profiles: disable `STEP_LOG` and verbose debug by default.

## 6. Related Documents

- `docs/operations/TROUBLESHOOTING.md`
- `docs/requirements/SECURITY_REQUIREMENTS.md`
- `docs/engineering/CONFIGURATION.md`
