# Hybrid AI Gateway — Coding Standards

Version: 1.0

Last reviewed: 13 July 2026

Status: engineering conventions derived from `AGENTS.md`, PRD §15.4, and architecture principles

## 1. Purpose

Keep changes small, consistent with existing patterns, and honest about Implemented vs Target vs Gap.

## 2. Inspect Before Edit

- Trace the relevant flow end to end (route → controller → service → config → tests → docs).
- Prefer existing helpers, services, repository mixins, and response conventions.
- Keep changes scoped; do not rename public routes or rewrite product claims casually.

## 3. Compatibility and Contracts

- Preserve `/v1/chat/completions`, `/chat`, `/v1/models`, `/memory/*`, `/mcp/*`, `/health/*`, `/metrics` unless intentionally changing and documenting.
- Move public boundaries toward typed schemas (API-002); avoid new unbounded `dict` trust-boundary APIs.
- Provider-specific logic belongs behind adapters (`SYSTEM_DESIGN.md`), not scattered controller conditionals.

## 4. Deterministic Authority

- Tool policy, memory scope, retention thresholds, network-search permission, and response modality are owned by application code — not model persuasion (PRD principles; FR-MCP-003).
- Approval-required tools must not execute until approval is granted and consumed.
- File paths stay under approved root after resolution; shell stays bounded.

## 5. Security and Privacy in Code

- Never log or commit provider keys, tokens, `.env` contents, credentials, or sensitive user data.
- Do not put raw approval IDs or secrets in metrics labels.
- Treat fetched media, memory text, and future web content as untrusted data.
- Fail closed on missing identity/policy/approval for consequential actions (SEC-015).

## 6. Memory and Pipeline

- Relational records authoritative; FAISS/pgvector derived.
- Resolve `memory_scope` before reads/writes.
- Keep chat fast path separate from routine memory writes when safe.
- Label docs with Implemented / Target / Gap; do not claim STT/TTS/search complete early.

## 7. Maintainability

- Architecture-impacting decisions need ADRs (`docs/planning/DECISIONS.md`).
- Prefer less code and root-cause fixes over speculative abstractions.
- Lint/format/typecheck/tests belong in CI (Target completeness).
- Update companion docs when behavior, setup, architecture, or requirements change.

## 8. Verification Before Done

Review: `git diff`, public routes/shapes, env impact, security implications, tests, docs. Never claim checks passed without running them.

## 9. Related Documents

- `AGENTS.md`
- `docs/engineering/GIT_WORKFLOW.md`
- `docs/engineering/TESTING_STRATEGY.md`
