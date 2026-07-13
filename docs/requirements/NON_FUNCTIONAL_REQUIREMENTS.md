# Hybrid AI Gateway — Non-Functional Requirements

Version: 1.0

Last reviewed: 13 July 2026

Status: extracted from `docs/PRD.md` §15; performance numbers are Target gates until measured on reference hardware

Authority: `docs/PRD.md`. Related: `docs/engineering/TESTING_STRATEGY.md`, `OBSERVABILITY.md`, `operations/DEPLOYMENT.md`.

## 1. Performance Targets

Exclude provider queueing when specifically stated; end-to-end reports must separate gateway overhead and provider time.

| ID | Metric | Initial target and condition | Status |
|---|---|---|---|
| NFR-PERF-001 | Gateway startup | Liveness ≤ 3 s p95; readiness ≤ 10 s p95 when local deps healthy (excl. provider inference) | Target |
| NFR-PERF-002 | Text gateway overhead | ≤ 150 ms p95 excl. memory retrieval and provider | Target |
| NFR-PERF-003 | Memory retrieval | ≤ 300 ms p95 at 100k indexed records (default FAISS) | Target |
| NFR-PERF-004 | First downstream stream event | Proxy within 100 ms after first valid upstream delta | Target |
| NFR-PERF-005 | Cancellation | Ack + upstream cancel attempt within 500 ms p95 | Target |
| NFR-PERF-006 | Tool approval lookup | ≤ 100 ms p95 for local MVP store at bounded capacity | Target |
| NFR-PERF-007 | Health | Liveness ≤ 50 ms p95; readiness ≤ 500 ms p95 (bounded/cached checks) | Target / Partial endpoints exist |
| NFR-PERF-008 | Media limits | Reject oversized input before full buffering where feasible | Partial |

## 2. Reliability and Recovery

| ID | Requirement | Status |
|---|---|---|
| NFR-REL-001 | Isolate memory/telemetry/optional-dep failures from successful chat where safe | Partial |
| NFR-REL-002 | No double-execution of sensitive tools from retry/approval replay | Gap |
| NFR-REL-003 | Vector corruption/incompatibility → recoverable degraded + reindex guidance | Partial |
| NFR-REL-004 | Queue outage → defined fallback/dead-letter; no silent discard | Partial |
| NFR-REL-005 | Provider timeouts/rate limits bounded; must not exhaust workers | Partial |
| NFR-REL-006 | Disk-full, RO storage, corrupt DB, unavailable Redis/Postgres, expired creds tested | Gap |
| NFR-REL-007 | Backup restore drill before production release | Gap |
| NFR-REL-008 | ≥ 99.5% successful gateway-handled text requests excl. provider failure and deliberate cancel (measured separately) | Target |

## 3. Resource Governance

Target controls (PRD §15.3):

- Bound concurrent upstream requests, media jobs, memory jobs, tool executions, subprocesses.
- Bound request body, tool output, stream duration, memory prompt budget, trace retention, log volume, metrics cardinality, index size.
- Prefer backpressure over unbounded queues.
- Do not load complete large files/media without enforced limits.
- Expose disk, database, vector, queue, and temp-storage health.
- Background memory/index work must not starve chat traffic.

**Implemented partial:** rate limits, some media/size limits, process-local metrics. **Gap:** multi-process/cluster-safe limits and full resource matrix.

## 4. Maintainability

From PRD §15.4:

- Lock Python/deps via approved reproducible strategy.
- Typed public boundaries and documented exceptions (API-002 Gap today).
- Contract tests for provider, vector, queue, and tool executor interfaces.
- Architecture-impacting decisions require ADRs (`docs/planning/DECISIONS.md`).
- CI: lint, format, type check, unit, integration, security, dependency checks (Gap: CI not yet authoritative).
- Legacy memory paths need documented retirement (OD-010).
- Configuration docs generated or verified against settings surface (`CONFIGURATION.md`).

## 5. Portability

MVP publishes a supported matrix (OD-013: Linux first), not universal claims. Minimum to choose and test:

- one primary Linux distribution/runtime profile;
- Docker Engine / Compose for Open WebUI;
- Python version;
- SQLite + FAISS default profile;
- optional PostgreSQL/pgvector and Redis/RQ versions;
- FFmpeg and yt-dlp when video support enabled.

macOS/Windows remain development or later until tested.

## 6. Related Success Metrics

Product/engineering gates in PRD §20.2 that act as NFR-adjacent gates include routing precision, memory quality, readiness usefulness, and recovery drill success. See `ACCEPTANCE_CRITERIA.md`.

## 7. Related Documents

- `docs/requirements/ACCEPTANCE_CRITERIA.md`
- `docs/engineering/TESTING_STRATEGY.md`
- `docs/operations/RELEASE_CHECKLIST.md`
