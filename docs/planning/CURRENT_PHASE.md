# Current Phase

Version: 1.0

Last reviewed: 13 July 2026

Status: living scope document — update when phase exits

## 1. Active Phase

**Product/architecture freeze → Phase 0 Foundation**

Companion documentation under `docs/` is being completed as freeze/Phase 0 contract work. Implementation of Phase 0 engineering readiness (typed schemas, migrations, loopback enforcement, CI, threat model) follows once scope docs are approved.

## 2. In Scope This Phase

- Approve PRD, architecture map, AI pipeline contract, trust boundaries, data-egress map, API subset
- Complete required companion documents (PRD Appendix F)
- Decide OD items needed by freeze/foundation (see §5)
- Establish CURRENT_PHASE exclusions for deferred work
- Begin Phase 0 foundation items once freeze exit is met: config validation, migrations plan, loopback default, auth decision, CI authority, dependency lock, threat model

## 3. Explicit Exclusions (Deferred)

| Item | Decision |
|---|---|
| STT / TTS / audio routes | OD-018 — defer from Phase 1 |
| Internet-search execution | OD-017 — defer from Phase 1 |
| Multi-provider failover | OD-015 — Phase 3 |
| Team multi-user / RBAC | Phase 5 |
| Fully local offline inference | Non-goal for MVP |
| Public internet exposure | Out of MVP |

## 4. Exit Criteria

### Freeze exit

- [ ] PRD and architecture authorities approved
- [ ] AI pipeline SoT accepted (OD-016)
- [ ] Companion docs no longer empty placeholders
- [ ] Supported platform direction chosen (OD-013)
- [ ] Data-egress map published

### Phase 0 exit (engineering readiness)

- [ ] Typed public schema plan underway / started
- [ ] Loopback enforcement plan or fix
- [ ] Auth decision recorded (OD-003)
- [ ] CI becomes runnable/authoritative
- [ ] Threat model draft exists
- [ ] Dependency lock strategy chosen

## 5. Blocking Open Decisions

| ID | Needed by | Topic |
|---|---|---|
| OD-002 | Freeze | Loopback-only MVP boundary |
| OD-003 | Foundation | Client authentication |
| OD-004 / OD-005 | API freeze | Aliases and OpenAI subset |
| OD-010 | Foundation | Memory architecture target |
| OD-011 | MVP scope | Default vector/queue profile |
| OD-012 | Immediately | Committed FAISS/runtime data |
| OD-013 | Roadmap | Supported OS |
| OD-015 | Freeze | NVIDIA-only Phase 1 |
| OD-016 | Immediately | AI_PIPELINE SoT |

Full register: `docs/planning/DECISIONS.md`.

## 6. Authority

Task work must respect PRD Appendix C hierarchy and this file’s exclusions. Template: `tasks/TASK_TEMPLATE.md`.

## 7. Related Documents

- `docs/ROADMAP.md`
- `docs/DEVELOPMENT_PLAN.md`
- `docs/planning/BACKLOG.md`
- `docs/PRD.md` §5 / §19
