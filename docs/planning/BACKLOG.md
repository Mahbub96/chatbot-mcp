# Backlog

Version: 1.0

Last reviewed: 13 July 2026

Status: phase-tagged Must/Should/Gap items linked to requirement IDs; not a commitment schedule

## 1. Sources

- PRD Must/Should requirements
- Architecture Gaps (`TECH_DEBT.md`)
- Open decisions (`DECISIONS.md`)
- AI pipeline implementation sequence (`AI_PIPELINE.md` §20)
- Explicit deferred list (PRD §5.4)

## 2. Freeze / Phase 0 — Foundation

| Item | IDs | Notes |
|---|---|---|
| Enforce loopback default bind | FR-GWY-001, TD-002, OD-002 | |
| Auth decision + design for non-loopback | OD-003, SEC-004 | |
| Typed public schemas plan | API-002, TD-005 | |
| Versioned migrations strategy | DATA-001, TD-013 | |
| Threat model document | SEC-001 | |
| CI + dependency lock | §15.4, TD-017 | |
| Remove/review committed FAISS artifacts | OD-012, TD-015 | |
| Config surface vs `.env.example` reconciliation | FR-GWY-004, TD-019 | |
| Memory architecture target selection | OD-010, TD-011 | |
| Default profile confirmation | OD-011 | |

## 3. Phase 1A — Core Gateway

| Item | IDs |
|---|---|
| NVIDIA adapter isolation | FR-PRV-*, TD-014 |
| Gateway aliases + capability metadata | FR-MOD-*, OD-004 |
| Stable error taxonomy | API-003, TD-018 |
| Streaming/cancellation contract complete | FR-CHAT-002/004 |
| Deterministic routing reason codes | FR-RTE-005 |

## 4. Phase 1B — Memory / Actions

| Item | IDs |
|---|---|
| Exact short-term retention across restart | FR-MEM-010, AI-PIPE-003, TD-012 |
| Normalized long-term facts + validation | FR-MEM-004/016, AI-PIPE-005/006 |
| Queue idempotency | FR-MEM-008, DATA-005 |
| Durable approvals | FR-MCP-004, OD-006, TD-003 |
| File sandbox root | FR-MCP-007, OD-007 |
| Shell allowlist hardening | FR-MCP-008, OD-008, TD-020 |

## 5. Phase 1C — Operations / Beta

| Item | IDs |
|---|---|
| Pin Open WebUI digest | FR-UI-001, TD-016 |
| Metrics/logs completeness | OPS-*, TD-004 |
| Backup/restore drill | NFR-REL-007 |
| Compatibility smoke (WebUI/Cursor) | FR-UI-005, FR-CUR-* |
| Packaging / known limitations | Release checklist |

## 6. Phase 2+ (Separate Approval)

| Item | IDs |
|---|---|
| Evidence sufficiency service | FR-CHAT-011, AI-PIPE-008/011, TD-009 |
| Policy-gated internet search | OD-017, AI_PIPELINE §10 |
| STT/TTS adapters | OD-018, VOICE_PIPELINE |
| Memory evaluation hardening | §9.3 metrics |
| Multi-provider platform | OD-015, Phase 3 |
| Team auth/RBAC/HA | Phase 5 |

## 7. Explicitly Deferred / Non-Goals for MVP

- Fully local offline inference
- Public internet exposure
- Multi-user tenancy
- Unattended high-risk autonomy
- General document RAG product
- Wake word / multi-agent orchestration

## 8. Related Documents

- `docs/planning/CURRENT_PHASE.md`
- `docs/ROADMAP.md`
- `docs/DEVELOPMENT_PLAN.md`
- `docs/requirements/FUNCTIONAL_REQUIREMENTS.md`
