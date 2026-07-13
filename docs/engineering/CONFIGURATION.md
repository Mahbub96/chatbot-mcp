# Hybrid AI Gateway — Configuration Reference

Version: 1.0

Last reviewed: 13 July 2026

Status: environment and profile companion; verify against `config.py` and `.env.example` to avoid drift (PRD §15.4)

## 1. Purpose

Centrally document configuration groups, deployment profiles, secrets handling, and Target knobs from `AI_PIPELINE.md` §18.

Authorities: FR-GWY-002/004/007; PRD §17.2; `config.py`; `.env.example`; `README.md`.

## 2. Principles

- Typed and validated where possible; invalid values should fail before readiness (Target completeness).
- No hard-coded secrets; use environment / secret references (SEC-003).
- Document Generated vs Observed: this file is maintained by hand today — Gap vs generated reference.
- Optional dependencies report degraded without blocking core text chat (FR-GWY-003).

## 3. Deployment Profiles (PRD §17.2)

| Profile | Purpose | Controls |
|---|---|---|
| Development | Local iteration | May use `SHORT_TERM_CLEAR_ON_RESTART=true`; debug logs OK |
| Workstation MVP | Trusted single operator | Loopback-first Target; SQLite+FAISS+in-process default (OD-011) |
| Team / shared | Authenticated multi-user | Requires auth, durable approvals, hardened network — Gap / Phase 5 |

## 4. Implemented Configuration Groups

### 4.1 Secrets and provider

| Variable | Role | Notes |
|---|---|---|
| `NVIDIA_API_KEY` | Required hosted provider credential | Must not be logged or committed |
| Chat/embed/image base URLs | Provider endpoints | Some URLs hardcoded in `config.py` despite `.env.example` `BASE_URL` — Gap |
| `STREAM_CHAT_READ_TIMEOUT_SECONDS` | Upstream stream read budget | Implemented |

### 4.2 Models and routing

| Variable | Role |
|---|---|
| `DEFAULT_MODEL` | Default upstream model |
| `BANGLA_MODEL` | Optional Bangla route |
| `CODE_MODEL` | Optional code route |
| `VISION_MODEL`, `VISION_FALLBACK_MODELS`, `VISION_SPEED_FIRST` | Vision routing |
| `IMAGE_GEN_MODEL`, `IMAGE_EDIT_MODEL` | Image proxy models |
| Vision/stream timeout knobs | Per-model and stream budgets |

### 4.3 Embeddings

`EMBEDDING_BASE_URL`, `EMBEDDING_MODEL`, `EMBEDDING_DIM`, `EMBEDDING_TIMEOUT_SECONDS`, `EMBEDDING_FAILURE_COOLDOWN_SECONDS` (latter used outside `config.py`).

### 4.4 Memory and queue

| Variable | Role | Production note |
|---|---|---|
| `MEMORY_ENABLED` | Gate memory in chat | |
| `MEMORY_SQLITE_URL` | Authoritative DB | |
| `MEMORY_VECTOR_*` / `PGVECTOR_*` | Derived index | Default FAISS |
| `MEMORY_TOP_K`, `MEMORY_MIN_SCORE` | Retrieval | |
| Semantic context fallback knobs | Soft fallback | Keep personal isolation |
| `MEMORY_AUTO_STORE`, promote thresholds | Promotion | |
| `SHORT_TERM_RETENTION_HOURS` | TTL | Target 24 |
| `SHORT_TERM_CLEAR_ON_RESTART` | Wipe short-term on boot | **Target production `false`**; `.env.example` often `true` (dev) |
| `MEMORY_QUEUE_BACKEND`, `MEMORY_REDIS_URL`, `MEMORY_RQ_QUEUE` | inprocess \| rq | |

### 4.5 Runtime / observability

| Variable | Role | Gap notes |
|---|---|---|
| `RATE_LIMIT_WINDOW_SECONDS`, `RATE_LIMIT_MAX_REQUESTS` | Process-local limiter | |
| `RATE_LIMIT_DISABLED` | In `.env.example` only | **Not wired** in `config.py` |
| `LOG_JSON`, `DEBUG_*`, `STEP_LOG_*` | Logging | Disable verbose debug in release |
| `SHADOW_MONITOR_*` | Shadow sampling | Some keys example-only |
| `HUMANIZE_RESPONSES` | Style prompt policy | Must not override safety |
| `GATEWAY_URL` | Cursor bridge target | |
| `MAX_TOOL_ACTIONS_PER_REQUEST` | Tool budget | Enforce in gateway |
| Media size/frame limits | Multimodal bounds | |

### 4.6 Documented but unwired / drift (Gap)

- `BASE_URL` in `.env.example` vs hardcoded chat base in `config.py`
- `RATE_LIMIT_DISABLED`
- Selected `TEXT_STREAM_*` / `SHADOW_MONITOR_MAX_RETRIEVAL_MS` example keys may not all map to `config.py`

Operators must treat `config.py` as the Implemented surface until a generated reference exists.

## 5. Target AI Pipeline Settings

From `AI_PIPELINE.md` §18 — **Target** until present in `config.py`:

| Variable | Intent |
|---|---|
| `STT_ENABLED` / `TTS_ENABLED` | Voice adapters |
| `DEFAULT_RESPONSE_MODE` | `text` / `speech` / `follow_input` |
| Network search enablement / provider | Policy-gated internet fallback |
| Evidence sufficiency thresholds | Formal sufficiency service |

## 6. Capability / Diagnostic Summary (Target)

FR-GWY-007: publish build version, configuration schema version, and enabled capability summary without secrets (health/diagnostics). Partial today via `/health/ready` and `/health/routes`.

## 7. Related Documents

- `docs/operations/LOCAL_SETUP.md`
- `docs/operations/DEPLOYMENT.md`
- `docs/architecture/SYSTEM_DESIGN.md`
- `docs/architecture/VOICE_PIPELINE.md`
