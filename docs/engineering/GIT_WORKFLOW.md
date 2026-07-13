# Hybrid AI Gateway — Git Workflow

Version: 1.0

Last reviewed: 13 July 2026

Status: source-control and review conventions from PRD Appendix C, FR-MEM-014, SEC-003/013, and AGENTS.md

## 1. Purpose

Keep the repository free of secrets and derived user data, preserve source-of-truth hierarchy, and require traceability for architecture changes.

## 2. Source-of-Truth Hierarchy

| Rank | Document | Owns |
|---|---|---|
| 1 | Approved PRD / ADR | Product and binding decisions |
| 2 | `docs/architecture/AI_PIPELINE.md` | Pipeline behavior (OD-016) |
| 3 | `docs/ARCHITECTURE.md` | System topology and trust |
| 4 | Companion docs under `docs/` | Detailed contracts |
| 5 | `docs/planning/CURRENT_PHASE.md` | Active scope for tasks |
| 6 | Code + tests | Observed behavior |

When code and docs disagree, inspect code, report the mismatch, and update the correct authority — do not silently change product intent in an unrelated PR.

## 3. What Must Not Be Committed

- Secrets: `.env`, API keys, tokens, credentials (SEC-003)
- Derived memory DBs, FAISS indexes, personal fixtures (FR-MEM-014, SEC-013, OD-012)
- Runtime artifacts that contain user data under `files/` unless explicitly sample and scrubbed
- Large binary dumps unrelated to source

## 4. Branch and Review Expectations

- Prefer small, reviewable commits with messages that explain **why**.
- Architecture-impacting changes require an ADR entry in `docs/planning/DECISIONS.md` (or linked ADR file).
- Security-sensitive PRs explicitly check leakage, traversal, injection, approval bypass, scope leakage, SSRF, secrets, unsafe logging.
- Do not force-push shared mainline branches; do not skip hooks unless explicitly requested by a human.

## 5. Traceability

Work items should cite PRD / AI-PIPE / SEC IDs (`tasks/TASK_TEMPLATE.md`). Definition of Done includes tests or explained inability to run them, and doc updates when contracts change.

## 6. Documentation-Only Changes

Minimum verification:

```bash
rg --files
rg -n "referenced/path/or/symbol" docs/
git diff -- docs/
```

## 7. Related Documents

- `docs/planning/DECISIONS.md`
- `docs/engineering/CODING_STANDARDS.md`
- `AGENTS.md`
