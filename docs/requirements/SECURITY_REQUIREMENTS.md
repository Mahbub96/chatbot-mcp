# Hybrid AI Gateway — Security Requirements

Version: 1.0

Last reviewed: 13 July 2026

Status: threat model, trust boundaries, SEC/PRI catalogs from `docs/PRD.md` §16 and `docs/ARCHITECTURE.md` §8; pipeline security from `AI_PIPELINE.md` §16

## 1. Purpose

This document owns **security and privacy requirements**, trust-boundary statements, and data-egress disclosure for the Hybrid AI Gateway.

Authority: `docs/PRD.md` §16. Architecture trust notes: `docs/ARCHITECTURE.md` §8. Pipeline: `docs/architecture/AI_PIPELINE.md` §16.

## 2. Threat Model Scope (SEC-001)

Threat model **Must** cover:

- local API exposure
- credential theft
- SSRF / DNS rebinding / redirect escape
- malicious media
- prompt injection
- memory poisoning and cross-scope leakage
- path traversal / symlink escape
- command injection
- approval replay / race
- dependency and model supply chain
- provider data egress

**Status:** Target formal threat-model artifact; known risks documented as Gaps below.

## 3. Trust Boundaries

| Boundary | Implemented | Target / Gap |
|---|---|---|
| Local gateway HTTP | Open routes; no client auth | Loopback-first; auth before shared/non-loopback (SEC-002/004) |
| Hosted NVIDIA provider | Chat, embeddings, vision, images leave machine | Minimize egress; adapter isolation; disclose always |
| Memory scope | App-level selector | Not authenticated tenancy; no identity bypass via cross-scope |
| Evidence / prompts | Memory injected into prompts | Formal evidence bundle; untrusted delimiters (SEC-006) |
| Tools / approvals | Deterministic policy; in-memory approvals | Durable actor-bound expiring approvals; hardened shell |
| Multimodal fetch | Broad URL/file handling with size limits | Production SSRF and trusted-root controls |
| Voice / search | Not present | Future adapters; search untrusted; STT/TTS wrap text pipeline |

## 4. Data-Egress Model

May leave the machine when applicable:

- user prompts and conversation messages for inference;
- selected memory snippets in provider prompts;
- image data, URLs, extracted frames, or metadata;
- prompts and source images for generation/editing;
- provider authentication and routing metadata.

Do **not** describe the product as private, local-only, offline, or zero-egress without qualification (PRI-001). Hybrid positioning is mandatory.

## 5. Security Requirements Catalog

| ID | Requirement | Status |
|---|---|---|
| SEC-001 | Complete threat model (see §2) | Gap |
| SEC-002 | Loopback by default; non-loopback needs authenticated profile, TLS, origin, network controls | Gap (binds `0.0.0.0`) |
| SEC-003 | Secrets via env/secret refs; never committed | Partial |
| SEC-004 | Authenticate admin/memory/tool ops before shared/non-loopback | Gap |
| SEC-005 | Authorization distinguishes chat, memory scopes, tools, approvals, diagnostics, config | Gap |
| SEC-006 | Memory, messages, media metadata, provider output, web content = untrusted data | Partial / Target |
| SEC-007 | Outbound URL policy: SSRF, DNS rebinding, restricted IPs, redirect escape, size | Gap |
| SEC-008 | Filesystem tools: canonical approved roots after symlink; least privilege | Partial |
| SEC-009 | Shell: deny-by-default command policy, exact approval binding, timeout, limits, sanitized env, cleanup | Gap |
| SEC-010 | Approvals: high-entropy, expiring, one-time, stateful, actor-bound, arg-bound, race/replay safe | Gap |
| SEC-011 | Logs/metrics/traces/memory/errors/support bundles redact secrets; minimize user content | Partial |
| SEC-012 | Scan/pin deps and images; SBOM and integrity for releases | Gap |
| SEC-013 | Derived memory/index with user data excluded from source distributions; protect permissions | Gap risk |
| SEC-014 | Image/video parsers/subprocesses least privilege and bounded resources | Partial |
| SEC-015 | Destructive/consequential actions fail closed when identity/policy/approval/config missing | Partial |

## 6. Privacy Requirements Catalog

| ID | Requirement | Status |
|---|---|---|
| PRI-001 | Accurate local vs hosted documentation | Partial |
| PRI-002 | Memory configurable, inspectable, exportable, deletable by scope | Partial (export Gap) |
| PRI-003 | Minimize provider-bound memory context | Partial |
| PRI-004 | No raw prompts/media/tool args in operational logs by default | Partial |
| PRI-005 | Support bundles preview data; default redacted | Gap |
| PRI-006 | Documented configurable retention for memory, traces, logs, approvals, media | Partial |
| PRI-007 | Link provider privacy terms from operator docs | Gap |

## 7. Responsible AI

From PRD §16.4:

- Model selection does not guarantee correctness.
- Provider output is not verified tool evidence.
- Do not claim visual analysis when only metadata was available.
- Attribute memory-derived statements when client experience supports it.
- Distinguish proposal, approval, execution, verification for tools.
- No autonomous high-stakes medical/legal/financial/security actions.
- Do not expose internal chain-of-thought; prefer concise route/retrieval/action summaries.

## 8. Pipeline Security Pointers

From `AI_PIPELINE.md` §16:

- Short-term exact text is as sensitive as long-term memory.
- Long-term extraction must not auto-store secrets.
- Cross-scope fallback prohibited by default.
- Search queries exclude unnecessary personal memory; results untrusted.
- Evidence delimiters defeat prompt injection from memory/web/tools.

## 9. Open Decisions

| ID | Topic | Needed by |
|---|---|---|
| OD-002 | Loopback-only MVP | Architecture freeze |
| OD-003 | Client authentication design | Foundation |
| OD-006 | Durable approvals | Tool hardening |
| OD-007 | File tool sandbox root | Security freeze |
| OD-008 | Shell allowlist policy | Security freeze |
| OD-009 | Media URL deny-by-default | Multimodal hardening |

See `docs/planning/DECISIONS.md`.

## 10. Related Documents

- `docs/architecture/TOOL_PERMISSION_MODEL.md`
- `docs/operations/DEPLOYMENT.md`
- `docs/engineering/OBSERVABILITY.md`
- `docs/requirements/ACCEPTANCE_CRITERIA.md`
