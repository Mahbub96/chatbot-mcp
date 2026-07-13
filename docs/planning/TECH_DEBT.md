# Technical Debt Ledger

Version: 1.0

Last reviewed: 13 July 2026

Status: known Gaps from `ARCHITECTURE.md` §10 and PRD §2.3 mapped to phases and OD IDs

## 1. Purpose

Track prototype risks that must not be mistaken for production guarantees.

## 2. Debt Items

| ID | Debt | Impact | Linked | Target phase |
|---|---|---|---|---|
| TD-001 | No client authentication/authorization | Unsafe if non-loopback or shared | SEC-004/005, OD-003 | Phase 0 / 5 |
| TD-002 | `start.sh` binds `0.0.0.0` | Contradicts loopback-first MVP | FR-GWY-001, OD-002 | Phase 0 |
| TD-003 | Process-local approvals; no actor/expiry/replay hardening | Approval bypass/replay risk | FR-MCP-004, OD-006, SEC-010 | Phase 1B |
| TD-004 | Process-local rate limit and metrics | Wrong under multi-worker | OPS-003, Phase 5 | Phase 1C / 5 |
| TD-005 | Loose public request/response dicts | Contract drift; unsafe inputs | API-002 | Phase 0 / 1A |
| TD-006 | No canonical request envelope / response_mode / evidence bundle | Pipeline incomplete | AI_PIPELINE, FR-CHAT-010–012 | Phase 1–2 |
| TD-007 | STT/TTS missing | Voice deferred | OD-018 | Phase 2+ |
| TD-008 | Internet search label without executor | Misleading intent | OD-017 | Phase 2+ / 3 |
| TD-009 | Evidence sufficiency incomplete | Fabrication / bad fallback risk | FR-CHAT-011 | Phase 2 |
| TD-010 | Media SSRF / trusted-root incomplete | Exfiltration if exposed | SEC-007, OD-009, FR-MM-* | Phase 1 multimodal |
| TD-011 | Dual legacy + new memory paths | Duplication; semantic risk | OD-010, FR-MEM-* | Phase 0–2 |
| TD-012 | `SHORT_TERM_CLEAR_ON_RESTART=true` default conflict | Breaks 24h TTL across restart | FR-MEM-010, AI-PIPE-003 | Phase 1B |
| TD-013 | Runtime `create_all` not migrations | Production schema risk | DATA-001 | Phase 0 |
| TD-014 | Provider logic not fully adapter-isolated | Harder multi-provider later | FR-PRV-*, OD-015 | Phase 1A / 3 |
| TD-015 | Committed FAISS / runtime user-data risk | Privacy / repo pollution | OD-012, FR-MEM-014 | Immediately |
| TD-016 | Floating Open WebUI `:main` tag | Non-reproducible UI | FR-UI-001 | Phase 1C |
| TD-017 | CI / deps not authoritative in inspection env | Unknown regression risk | PRD §2.3 | Phase 0 |
| TD-018 | Soft HTTP 200 errors on memory/MCP | Client contract ambiguity | API-003 | Phase 1A |
| TD-019 | `.env.example` keys unwired (`RATE_LIMIT_DISABLED`, `BASE_URL` drift) | Operator confusion | FR-GWY-004 | Phase 0 |
| TD-020 | Shell not production sandbox / allowlist incomplete | Command injection risk | OD-008, FR-MCP-008 | Phase 1B |

## 3. Related Documents

- `docs/planning/BACKLOG.md`
- `docs/planning/DECISIONS.md`
- `docs/ARCHITECTURE.md` §10
- `docs/requirements/SECURITY_REQUIREMENTS.md`
