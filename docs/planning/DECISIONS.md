# Decisions Register

Version: 1.0

Last reviewed: 13 July 2026

Status: open decisions from PRD §21.3 plus positioning decisions; promote to ADR files under `docs/architecture/ADR/` when approved

## 1. How Decisions Are Recorded

- **Pending:** recommendation exists; not yet product-owner approved
- **Approved:** binding; update PRD/architecture companions if needed
- **Superseded:** replaced by a later ADR

Architecture-impacting changes require an ADR (PRD §15.4).

## 2. Positioning Decisions (Working)

| Topic | Working decision | Status |
|---|---|---|
| Product name | Hybrid AI Gateway (repo may remain `chatbot-mcp`) | Pending public brand (OD-001) |
| Deployment | Trusted single-operator, loopback-only MVP | Pending approval (OD-002) |
| Inference | Hybrid: local control plane; hosted NVIDIA inference | Approved direction in PRD |
| Pipeline SoT | `docs/architecture/AI_PIPELINE.md` | Pending formal OD-016 sign-off |
| Phase 1 provider | NVIDIA only | Pending OD-015 |

## 3. Open Decisions Register

| ID | Decision | Recommendation | Needed by | Status |
|---|---|---|---|---|
| OD-001 | Product name | Use “Hybrid AI Gateway”; repo may stay `chatbot-mcp` until brand decision | Public beta | Pending |
| OD-002 | MVP deployment boundary | Trusted single-operator, loopback-only | Architecture freeze | Pending |
| OD-003 | Client authentication | No auth only for enforced loopback MVP; design token/auth before network exposure | Foundation | Pending |
| OD-004 | Gateway model aliases | Stable aliases rather than provider IDs as client contract | API freeze | Pending |
| OD-005 | OpenAI compatibility subset | Publish exact supported fields and extensions | API freeze | Pending |
| OD-006 | Approval persistence | Durable SQLite approval/execution records for MVP | Tool hardening | Pending |
| OD-007 | File tool root | Dedicated configured sandbox directory | Security freeze | Pending |
| OD-008 | Shell policy | Deny-by-default allowlisted commands/args + per-action approval | Security freeze | Pending |
| OD-009 | Media URL policy | Deny private/local by default; local files only in trusted-root mode | Multimodal hardening | Pending |
| OD-010 | Memory architecture | New repository/service as target; document legacy migration | Foundation | Pending |
| OD-011 | Default vector/queue profile | SQLite + FAISS + in-process for workstation; Postgres/Redis later | MVP scope freeze | Pending |
| OD-012 | Committed FAISS artifact | Remove from active source tree; review history for sensitive content | Immediately | Pending |
| OD-013 | Supported OS | Linux first; macOS/Windows later until tested | Roadmap approval | Pending |
| OD-014 | Image-generation scope | Retain in MVP only if provider contract stable under test | MVP scope freeze | Pending |
| OD-015 | Provider fallback | NVIDIA only in MVP; multi-provider in Phase 3 | Architecture freeze | Pending |
| OD-016 | AI pipeline SoT | Treat `AI_PIPELINE.md` as authoritative for pipeline topics | Immediately | Pending |
| OD-017 | Internet-search fallback | Defer from Phase 1; later local-first, policy-gated, no personal-miss auto-search | Retrieval/search phase | Pending |
| OD-018 | STT/TTS scope | Defer from Phase 1; adapters wrap text pipeline; TTS failure preserves text | Voice phase approval | Pending |

## 4. Related Documents

- `docs/planning/CURRENT_PHASE.md`
- `docs/planning/TECH_DEBT.md`
- `docs/PRD.md` §21.3
- `docs/engineering/GIT_WORKFLOW.md`
