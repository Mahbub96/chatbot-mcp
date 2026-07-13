# Hybrid AI Gateway — Roadmap

Version: 1.0

Last reviewed: 13 July 2026

Status: planning ranges from `docs/PRD.md` §5.1 and §19 — not delivery commitments

## 1. Overview

Durations are indicative. Provider contracts, auth scope, approval persistence, memory consolidation, platform count, and security findings can change delivery.

Current repository is a **prototype baseline** (Observed/Implemented). Phase exits require acceptance gates in `ACCEPTANCE_CRITERIA.md`.

## 2. Stage Table (PRD §19)

| Stage | Indicative duration | Key deliverables | Exit decision |
|---|---|---|---|
| Product/architecture freeze | 2–3 weeks | Approved PRD, architecture map, AI pipeline contract, trust boundaries, platform, egress map, API subset | Scope approved |
| Phase 0 — Foundation | 4–6 weeks | Typed schemas, config validation, migrations, loopback, auth decision, CI, lockfile, threat model | Engineering readiness |
| Phase 1A — Core gateway | 5–7 weeks | NVIDIA adapter, aliases/capabilities, routing, stable errors, streaming/cancellation | Core acceptance |
| Phase 1B — Memory/actions | 5–7 weeks | Memory consolidation, exact ST / normalized LT, queue, durable approvals, file/shell hardening | Security acceptance |
| Phase 1C — Operations/beta | 3–5 weeks | WebUI/Cursor compatibility, metrics/logs, performance, backup/restore, packaging, docs | Private beta |
| Release hardening | 3–4 weeks | Adversarial testing, remediation, release artifacts, supported matrix, RC soak | v1.0 go/no-go |
| Phase 2+ | Separate approval | Evidence sufficiency, internet fallback, STT/TTS, retrieval hardening, providers, governed tools, team deploy | Per-phase PRD/ADR |

## 3. Capability Phases (PRD §5.1)

| Phase | Outcome | Deferred from that phase |
|---|---|---|
| 0 Foundation | Trustworthy engineering baseline | New user-facing breadth |
| 1 Production MVP | Reliable hybrid gateway for trusted operator | Multi-provider, enterprise multi-user, full local inference |
| 2 Memory & retrieval hardening | Measurable governable memory + evidence sufficiency | Document KB platform |
| 3 Provider and evidence platform | Provider registry + optional search adapter | Marketplace/billing |
| 4 Governed tools | Stronger sandbox, durable approvals, more tools | Unattended high-risk autonomy |
| 5 Team deployment | Identity, tenancy, RBAC, distributed ops | Public multi-tenant SaaS unless separately approved |

## 4. MVP Definition Pointer

Phase 1 is MVP: trusted operator, NVIDIA-hosted inference, OpenAI-compatible chat, routing, scoped memory, bounded MCP tools with approval, diagnostics. Not complete merely because routes execute — must pass security, compatibility, failure-mode, recovery, docs, and release criteria (`PRD.md` §5.2–5.4).

## 5. Success Metrics Gate

Phase exits should consult PRD §20 and `ACCEPTANCE_CRITERIA.md` (routing ≥95% modality-safe, memory P@5, zero cross-scope leakage, tool approval integrity, etc.).

## 6. Related Documents

- `docs/DEVELOPMENT_PLAN.md`
- `docs/planning/CURRENT_PHASE.md`
- `docs/planning/BACKLOG.md`
- `docs/PRD.md` §19
