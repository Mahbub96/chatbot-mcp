# Hybrid AI Gateway — Release Checklist

Version: 1.0

Last reviewed: 13 July 2026

Status: MVP exit and product-owner gates from PRD §18.2 and Appendix G

## 1. Purpose

Go/no-go checklist before calling a build a production MVP release for the trusted workstation profile.

## 2. Requirements and Security

- [ ] All Phase 0/1 Must requirements implemented or formally waived (owner, rationale, risk, expiry)
- [ ] No open Critical/High security issues
- [ ] No known authorization, scope-isolation, approval-bypass, arbitrary-command, traversal, or SSRF vulnerability
- [ ] Threat model reviewed (`SECURITY_REQUIREMENTS.md`)
- [ ] Data-egress map accurate and disclosed (`DEPLOYMENT.md`)

## 3. Network and Auth

- [ ] Loopback-only default verified in release artifacts (FR-GWY-001)
- [ ] Non-loopback profile (if any) has auth/TLS/network controls documented
- [ ] Auth decision recorded (OD-003)

## 4. Provider and API

- [ ] NVIDIA invalid-key, quota/rate-limit, model-unavailable, timeout, malformed-response, service-error contract tests pass
- [ ] Streaming and non-streaming compatibility tests pass for documented subset
- [ ] OpenAI-compatible subset and deviations published (`API_DESIGN.md`)
- [ ] Gateway aliases/capabilities documented (OD-004/005)

## 5. Memory and Tools

- [ ] Memory add/search/list/delete/reindex and cross-scope isolation pass
- [ ] Short-term production restart retention validated (or waiver)
- [ ] Sensitive tool approval binding, expiry, replay protection, execution evidence pass
- [ ] File root and shell policy approved (OD-007/008)

## 6. Performance and Recovery

- [ ] NFR performance targets measured on reference hardware (provider time separate)
- [ ] Backup restore drill passed (NFR-REL-007)
- [ ] Clean install and upgrade/restore on supported matrix

## 7. Documentation Gate

Approved and current:

- [ ] Architecture + AI pipeline
- [ ] API contract
- [ ] Configuration reference
- [ ] Operations / local setup / troubleshooting
- [ ] Security requirements
- [ ] This release checklist
- [ ] Known limitations listed

## 8. Release Artifacts

- [ ] Locked dependencies
- [ ] Container reference/digest for Open WebUI (and gateway if packaged)
- [ ] SBOM and integrity checksums (SEC-012)
- [ ] Known limitations document
- [ ] Version / capability diagnostic fields (FR-GWY-007)

## 9. Product Owner Review (Appendix G)

- [ ] Confirm Hybrid positioning; reject fully-local/offline MVP claims
- [ ] Approve trusted single-operator loopback-only MVP
- [ ] Approve NVIDIA-only Phase 1 provider
- [ ] Approve OpenAI-compatible API subset
- [ ] Approve stable aliases and routing precedence
- [ ] Approve memory defaults, retention, egress disclosure
- [ ] Approve durable approvals and shell/file risk policies
- [ ] Approve media URL deny-by-default / trusted-root exception
- [ ] Decide image gen/edit MVP retention after contract tests
- [ ] Approve Linux-first platform (or nominate tested target)
- [ ] Remove/review committed runtime memory artifacts
- [ ] Assign engineering, security, QA, memory, provider, operations owners

## 10. Related Documents

- `docs/requirements/ACCEPTANCE_CRITERIA.md`
- `docs/planning/CURRENT_PHASE.md`
- `docs/PRD.md` §18–20
