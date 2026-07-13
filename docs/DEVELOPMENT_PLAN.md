# Hybrid AI Gateway — Development Plan

Version: 1.0

Last reviewed: 13 July 2026

Status: executable workstream plan under PRD phases; detailed backlog in `docs/planning/BACKLOG.md`

## 1. Purpose and Authority

This plan sequences engineering work. Product scope and Must requirements remain in `docs/PRD.md`. Pipeline sequencing detail for AI behavior is owned by `docs/architecture/AI_PIPELINE.md` §20. Active exclusions live in `docs/planning/CURRENT_PHASE.md`.

## 2. Product Outcomes (Pointers)

- Governed local control plane with hosted NVIDIA inference (hybrid)
- Scoped memory with exact short-term and normalized long-term facts
- Deterministic tool policy and approvals
- Honest evidence / no-result behavior (Target completeness)
- Operator diagnostics without secret leakage

MVP definition: PRD §5.2–5.4.

## 3. Workstreams (PRD §19.1)

| Workstream | Owns |
|---|---|
| Product | Scope, clients, compatibility subset, metrics, release policy |
| Gateway/API | Typed schemas, streaming, errors, cancellation, lifecycle |
| Provider/routing | NVIDIA adapter, capabilities, fallback, evaluation |
| AI pipeline | Envelope, ST/LT memory lanes, evidence bundle/sufficiency, modality |
| Memory | Schema/migrations, extraction, retrieval, vectors, queue, TTL |
| MCP/security | Registry, policy, approvals, sandbox, audit |
| Multimodal | URL policy, media processing, vision/image safety |
| Operations | Config, health, metrics, logging, backup, packaging, supply chain |
| Quality | Fixtures, stubs, integration envs, security/perf/recovery tests |

## 4. Phase Work Packages

### Freeze

Approve SoT docs; complete companions; resolve OD-002/015/016; publish egress map.

### Phase 0

Loopback enforcement; config validation; migrations approach; auth decision; CI; lockfiles; threat model; remove unsafe committed runtime data (OD-012).

### Phase 1A

Adapter boundary; aliases; routing observability; error taxonomy; chat stream/cancel contracts.

### Phase 1B

Memory consolidation; production ST retention; LT validation/dedup; durable approvals; file/shell hardening.

### Phase 1C

Pin UI; observability completeness; performance budgets; backup drill; packaging; private beta docs.

### Hardening

Adversarial security suite; remediations; SBOM/checksums; supported matrix; RC soak → v1.0 gate.

### Phase 2+

Evidence sufficiency; policy-gated search; STT/TTS; further retrieval/provider/tool/team work per separate approval.

## 5. AI Pipeline Implementation Sequence

From `AI_PIPELINE.md` §20 (do not reorder casually):

1. Canonical request envelope and response-mode contract
2. Separate short-term exact capture from long-term candidate processing
3. Production short-term restart → TTL retention
4. Long-term classifier JSON schema validation
5. Idempotent fact dedup, conflicts, embedding status
6. Explicit evidence-sufficiency service
7. Search-provider interface and secure network policy
8. Memory-first, policy-gated internet fallback
9. Evidence bundle and grounded response prompt contract
10. STT input adapter + transcript confirmation
11. TTS output adapter + text-preserving fallback
12. Integration, security, performance, TTL, failure-mode tests

Steps 7–11 are largely Phase 2+ / deferred relative to Phase 1 MVP.

## 6. Ready / Done Linkage

- DoR: PRD §18.3 + `tasks/TASK_TEMPLATE.md`
- DoD: PRD §22.2 + `ACCEPTANCE_CRITERIA.md`
- Release gate: `operations/RELEASE_CHECKLIST.md`

## 7. Dependencies and Risks

External: NVIDIA availability/terms, Open WebUI upgrades, FFmpeg/yt-dlp, optional Redis/Postgres.

Schedule risks: OD-003 auth, OD-006 approvals, OD-010 memory consolidation, security findings (PRD §21.1).

## 8. Related Documents

- `docs/ROADMAP.md`
- `docs/planning/BACKLOG.md`
- `docs/planning/TECH_DEBT.md`
- `docs/architecture/AI_PIPELINE.md`
