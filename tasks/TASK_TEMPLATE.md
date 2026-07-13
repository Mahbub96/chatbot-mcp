# Task Template

Version: 1.0

Last reviewed: 13 July 2026

Status: Definition of Ready / traceability template from `docs/PRD.md` §18.3 and §22.1

Copy this file (or its sections) into a new task/issue. Do not start implementation until DoR fields are complete or explicitly waived by the phase owner.

---

## Title

<!-- Short outcome-oriented title -->

## Owner / Phase

- Owner:
- Phase: <!-- see docs/planning/CURRENT_PHASE.md -->
- Workstream: <!-- Product / Gateway/API / Provider / AI pipeline / Memory / MCP / Multimodal / Operations / Quality -->

## User Outcome

<!-- What the operator or client can do when this is done -->

## Requirement IDs

- PRD / FR / NFR / SEC / OPS / DATA / API / AI-PIPE:
- Related OD / TD:

## Current vs Target Behavior

| Aspect | Current (Observed) | Target |
|---|---|---|
| Behavior | | |
| Status label | Implemented / Partial / Gap | Target |

## Design Artifacts Impacted

- [ ] API (`docs/architecture/API_DESIGN.md`)
- [ ] Data model (`DATA_MODEL.md`)
- [ ] Memory/RAG (`MEMORY_AND_RAG.md`)
- [ ] System design / routing (`SYSTEM_DESIGN.md`)
- [ ] Tools/approvals (`TOOL_PERMISSION_MODEL.md`)
- [ ] Voice (`VOICE_PIPELINE.md`) — only if in scope
- [ ] Security (`SECURITY_REQUIREMENTS.md`)
- [ ] Config / observability / ops docs
- [ ] ADR required? (`docs/planning/DECISIONS.md`)

## Failure / Cancel / Retry / Recovery

| Case | Expected behavior | Test idea |
|---|---|---|
| Validation failure | | |
| Provider failure | | |
| Cancellation | | |
| Retry / idempotency | | |
| Degraded dependency | | |

## Dependencies and Open Decisions

- Blocked on:
- OD IDs needing resolution:
- External deps:

## Acceptance Criteria

<!-- Measurable checks; link ACCEPTANCE_CRITERIA.md / AI-PIPE IDs -->

1.
2.
3.

## Validation Commands

```bash
# Exact commands to run; do not claim pass without running
python3 -m pytest path/to/tests
```

## Security / Privacy Checklist

- [ ] Secrets not logged or committed
- [ ] Scope / auth implications considered
- [ ] SSRF / path / shell / approval bypass reviewed if touched
- [ ] Egress disclosure still accurate if provider/media/memory changed
- [ ] Metrics labels bounded; no sensitive label values

## Observability Impact

- New/changed logs, metrics, health signals:
- Redaction notes:

## Docs / Release Notes

- Docs to update:
- Known limitations:
- Release checklist items affected:

## Evidence Links

- Tests:
- Metrics / logs samples (redacted):
- Screenshots (only if needed):

## Waiver / Deviation (if any)

- Requirement waived:
- Owner:
- Rationale:
- Risk:
- Expiry:

## Definition of Done Sign-off

- [ ] DoR was complete before coding
- [ ] CURRENT_PHASE exclusions respected
- [ ] Tests run or inability explained
- [ ] Docs updated
- [ ] Security implications reviewed
- [ ] No silent PRD/architecture intent change
