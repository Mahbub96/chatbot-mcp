# Hybrid AI Gateway — Tool Permission Model

Version: 1.0

Last reviewed: 13 July 2026

Status: risk taxonomy, approval state machine, sandbox, and audit companion

## 1. Purpose

This document owns **tool risk classes, deterministic policy, approval binding, sandbox rules, evidence, and audit**.

Authorities: `docs/PRD.md` §10; `docs/ARCHITECTURE.md` §5.5 / §8.5; observed `permissions/policy.py`, `permissions/approvals.py`, `gateway/controllers/tool_controller.py`, `tools/*`.

## 2. Capability Model

Tools are registered capabilities with schemas and risk metadata. Discovery exposes only registered, enabled tools (FR-MCP-001). Unknown or import-failed tools are unavailable with diagnostics.

**Implemented tools (examples):**

| Tool | Actions | Default policy |
|---|---|---|
| `file_tools` | list/read/write/delete under approved root | write/delete → approval; read/list → allow |
| `shell_command` | run command | always approval |

Cursor bridge (`cursor_mcp_server.py`) forwards to gateway HTTP and **must not** become an alternate authorization path (FR-MCP-013).

## 3. Risk Classes (PRD §10.2)

| Class | Examples | Default policy |
|---|---|---|
| R0 — Informational | Health, list tools | Allow locally; bounded logging |
| R1 — Scoped read | List/read under approved root | Allow per root/client policy |
| R2 — Reversible mutation | Create/write/rename in root | Exact preview + one-time approval by default |
| R3 — Consequential | Delete, shell, network-changing | Per-action approval, strict binding, strong evidence |
| R4 — Prohibited | Credential extraction, root escape, disabling policy | Deny in MVP |

## 4. Deterministic Policy

**Implemented** in `evaluate_tool_action()`:

- `shell_command` → approval required, risk `high`
- `file_tools` write/delete → approval required, risk `medium`
- other `file_tools` actions → allow, risk `low`
- unknown tools → approval required by default

**Rules:**

- Policy is independent of model persuasion (FR-MCP-003).
- Arguments validate before approval creation or execution (FR-MCP-002).
- Maximum tool actions per request enforced by gateway (FR-MCP-014).

## 5. Approval State Machine

### 5.1 Target states (FR-MCP-009)

`requested` → `approval_required` → `approved` | `denied` | `expired` → `executing` → `succeeded` | `partially_succeeded` | `failed` | `cancelled`

Clients must never infer completion from approval alone.

### 5.2 Implemented flow

1. Execute without `approval_id` when policy requires approval → create pending approval, return `requires_approval` + `approval_id`.
2. `POST /mcp/approve` records decision.
3. Re-execute with matching `approval_id` and argument hash → consume once → run tool.
4. Rejection must not execute side effects (FR-MCP-005).

### 5.3 Target binding (FR-MCP-004 / OD-006)

Approvals MUST bind: client/actor context, tool version, normalized arguments, target scope, risk, creation time, expiry, one-time use. Modified, replayed, or expired approvals are rejected.

| Aspect | Implemented | Target |
|---|---|---|
| Storage | In-memory process store | Durable SQLite (or equivalent) |
| Actor binding | Gap | Required |
| Expiry | Gap | Required |
| Race/replay hardening | Gap | Required |
| Audit immutability | Gap | Required |

## 6. Filesystem Sandbox

**Implemented:** file tools operate under configured/approved root (typically `files/`).

**Target / Must (FR-MCP-007, OD-007):**

- Canonicalize paths after symlink resolution.
- Remain under approved root.
- Prefer a dedicated sandbox directory, not repository/global filesystem.
- Deny traversal and symlink escape (security tests).

Reversible mutations should prefer trash/staging or undo references where practical (FR-MCP-011 Should).

## 7. Shell Policy

**Implemented:** shell requires approval; bounded working directory, timeout, and output limits exist as guardrails — **not** a production sandbox.

**Target / Must (FR-MCP-008, OD-008):**

- Explicit command allowlist / deny policy.
- Do not interpolate untrusted arguments into a shell string implicitly.
- Prefer argv execution; reject injection fixtures.
- Enforce timeout, cancellation, output limits, cwd, environment allowlist, child cleanup (FR-MCP-006).

**Gap:** broadening shell capability requires explicit justification; strengthening is welcome.

## 8. Execution Evidence and Redaction

- Success requires observable postconditions or executor evidence (FR-MCP-010).
- Tool output and audit must redact configured secrets and sensitive env values (FR-MCP-012).
- Never log raw approval IDs as high-cardinality metric labels or leak secrets in metrics.

## 9. Requirements Catalog

FR-MCP-001…014 are listed with acceptance in `docs/requirements/FUNCTIONAL_REQUIREMENTS.md` and `ACCEPTANCE_CRITERIA.md`. Security implications in `SECURITY_REQUIREMENTS.md` (SEC-007…011).

## 10. Related Documents

- `docs/architecture/API_DESIGN.md` — MCP routes
- `docs/ARCHITECTURE.md` — trust boundary §8.5
- `docs/planning/DECISIONS.md` — OD-006…008
- `docs/planning/TECH_DEBT.md` — approval/shell gaps
