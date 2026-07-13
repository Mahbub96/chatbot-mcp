# Hybrid AI Gateway — Acceptance Criteria

Version: 1.0

Last reviewed: 13 July 2026

Status: acceptance gates extracted from `docs/PRD.md` §18–20 and `docs/architecture/AI_PIPELINE.md` §19

## 1. Vocabulary

| Term | Meaning |
|---|---|
| Must / Should | PRD priority |
| Observed / Implemented | Present in repository baseline |
| Target | Required future behavior |
| Deferred | Explicitly out of current phase |
| Waiver | Must requirement formally waived with owner, rationale, risk, expiry |

Per-requirement acceptance summaries live beside FR/NFR/SEC IDs in:

- `docs/requirements/FUNCTIONAL_REQUIREMENTS.md`
- `docs/requirements/NON_FUNCTIONAL_REQUIREMENTS.md`
- `docs/requirements/SECURITY_REQUIREMENTS.md`
- `docs/PRD.md` (authoritative wording)

## 2. Definition of Ready (task intake)

A delivery item is ready when (PRD §18.3):

- PRD requirement IDs and user outcome are identified;
- current versus target behavior is understood;
- API/data/security/observability impacts are specified;
- failure, cancellation, retry, and recovery behavior are testable;
- dependencies and open decisions have owners;
- acceptance criteria and validation commands are defined.

Use `tasks/TASK_TEMPLATE.md`.

## 3. AI Pipeline Acceptance (AI-PIPE-001…015)

| ID | Acceptance criteria | Phase note |
|---|---|---|
| AI-PIPE-001 | Equivalent text and speech inputs → equivalent routing/retrieval | Voice Deferred |
| AI-PIPE-002 | Retrieved short-term trace matches accepted wording and metadata | Phase 1 |
| AI-PIPE-003 | Restart retains unexpired rows; TTL deletes expired | Phase 1 (fix Gap) |
| AI-PIPE-004 | Classifier/embedding delay does not add to answer latency | Phase 1 |
| AI-PIPE-005 | Fixtures produce structured facts; reject conversational noise | Phase 1–2 |
| AI-PIPE-006 | Malformed/secret-like/low-confidence/low-importance rejected | Phase 1 |
| AI-PIPE-007 | Cross-scope isolation and stage-order tests pass | Phase 1 |
| AI-PIPE-008 | Sufficient local evidence → zero search requests | Phase 2+ search |
| AI-PIPE-009 | Personal miss → local not-found; no auto web search | Phase 2+ search |
| AI-PIPE-010 | Prompt-injection pages cannot change system/tool policy | Phase 2+ search |
| AI-PIPE-011 | No-result tests contain no fabricated facts/citations | Phase 2 |
| AI-PIPE-012 | TTS failure returns text + nonfatal warning | Voice Deferred |
| AI-PIPE-013 | Complete/partial/cancelled/failed traces distinguishable | Phase 1 |
| AI-PIPE-014 | Embed failure keeps fact via structured/lexical retrieval | Phase 1 |
| AI-PIPE-015 | Logs and jobs share one correlation ID end to end | Phase 1 |

## 4. Required Test Layers (PRD §18.1)

| Layer | Required coverage |
|---|---|
| Unit | Routing, intent, schema validation, scoring/filtering, policy, path/URL, approval state, error mapping |
| Contract | OpenAI subset, SSE, NVIDIA adapter, vector/queue, MCP bridge, image endpoints |
| Integration | FastAPI + DB/index, provider stub, Redis/RQ, pgvector, tool executor, Open WebUI smoke |
| End-to-end | Startup, models, chat stream/non-stream, cancel, memory lifecycle, approval, file sandbox, provider failures, readiness |
| Security | SSRF, traversal, symlink, command injection, approval replay/race, prompt injection, memory leak, secret redaction |
| Performance | Overhead, first-event latency, retrieval scale, queue backpressure, stream soak, media limits |
| Recovery | Disk full, corrupt index, DB down, Redis loss, interrupted job, provider timeout, expired key, graceful shutdown |
| Compatibility | Pinned Open WebUI, Cursor bridge, documented curl/Python examples |

Current suite status and mapping: `docs/engineering/TESTING_STRATEGY.md`.

## 5. MVP Exit Criteria (PRD §18.2)

Checklist — all must pass or be formally waived:

- [ ] All Phase 0/1 Must requirements implemented or waived (owner, rationale, risk, expiry)
- [ ] No open Critical/High security issues; no known auth, scope-isolation, approval-bypass, arbitrary-command, traversal, or SSRF vulnerability
- [ ] Loopback-only default verified in release artifacts
- [ ] NVIDIA invalid-key, quota/rate-limit, model-unavailable, timeout, malformed-response, service-error contract tests pass
- [ ] Streaming and non-streaming compatibility tests pass for documented API subset
- [ ] Memory add/search/list/delete/reindex and cross-scope isolation pass
- [ ] Sensitive tool approval binding, expiry, replay protection, and execution evidence pass
- [ ] Performance targets pass on approved reference hardware (provider time separate)
- [ ] Clean install and upgrade/restore on supported platform matrix
- [ ] Threat model, data-egress map, API contract, configuration reference, operations guide, security guide, release checklist approved
- [ ] Release includes locked dependencies, container reference/digest, SBOM, checksums, known limitations

Operational mirror: `docs/operations/RELEASE_CHECKLIST.md`.

## 6. Success Metric Gates (PRD §20.2)

| Category | Metric | Initial target |
|---|---|---|
| Activation | Clean setup → first successful chat | ≥ 85% controlled beta |
| Compatibility | Supported client contract pass rate | 100% release suite |
| Gateway reliability | Successful gateway-handled text excl. provider failures | ≥ 99.5% |
| Routing | Correct route on labeled dataset | ≥ 95%; 100% modality safety |
| Memory | Precision@5 | ≥ 0.80 |
| Memory safety | Cross-scope leakage | 0 |
| Memory quality | Auto-store pollution | ≤ 5% reviewed sample |
| Evidence | No-result correctness | 100% fixtures; no fabricated facts |
| Search restraint | Unnecessary search when local sufficient | 0 once search exists |
| Tool safety | Consequential actions approval-gated | 100% |
| Tool integrity | Replay / arg-mismatch execution | 0 |
| Security | Restricted URL/path/command bypass | 0 |
| Operations | Actionable provider failure classification | ≥ 95% contract scenarios |

North-star: weekly successful governed AI tasks without unrecovered gateway error, unauthorized action, scope leak, or repeated correction from routing/memory failure.

## 7. Product Definition of Done (PRD §22.2)

A product increment is done when requirement IDs are implemented or waived, tests and security checks for the touched surface pass, observability and docs are updated, and release/ops impacts are recorded. Traceability model: requirement → design → code → test → evidence.

## 8. Related Documents

- `docs/engineering/TESTING_STRATEGY.md`
- `docs/operations/RELEASE_CHECKLIST.md`
- `tasks/TASK_TEMPLATE.md`
- `docs/architecture/AI_PIPELINE.md`
