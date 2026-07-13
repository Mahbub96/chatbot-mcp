# Hybrid AI Gateway — Deployment

Version: 1.0

Last reviewed: 13 July 2026

Status: workstation MVP and profile controls; team deployment is later phase

## 1. Purpose

Document deployment profiles, network exposure, Open WebUI packaging, storage, backups, upgrades, and data egress.

Authorities: PRD §16.1, §17.2–17.3; FR-GWY-001; FR-PRV-005; `ARCHITECTURE.md`; `start.sh`.

## 2. Deployment Profiles

| Profile | Purpose | Required controls | Status |
|---|---|---|---|
| Local development | One developer | `.env`, cautious debug, SQLite/FAISS, in-process queue | Implemented path |
| Trusted workstation MVP | One operator + Open WebUI/Cursor | Loopback-first, restrictive files, logging/retention, backups, pinned UI | Target (bind Gap) |
| Team/internal | Multiple authenticated users | TLS, identity, RBAC, scoped memory, durable approvals, Postgres/pgvector, Redis/RQ, distributed limits | Deferred Phase 5 |

## 3. Network and Auth

| Rule | Status |
|---|---|
| Default bind `127.0.0.1` (FR-GWY-001, OD-002) | Gap — `start.sh` uses `0.0.0.0` |
| No client auth on routes | Gap — safe only as loopback trusted operator assumption |
| Non-loopback requires authenticated profile, TLS, origin, network controls (SEC-002/004) | Target |

Do not expose the gateway to the public internet with current code.

## 4. Open WebUI

**Implemented by `start.sh`:**

- Image: `ghcr.io/open-webui/open-webui:main` (floating tag — Gap vs FR-UI-001 pin/digest)
- Port: host `3000` → container `8080`
- Volumes: `open-webui-data`, `hf-cache`
- `OPENAI_API_BASE_URL=http://host.docker.internal:8000/v1` with dummy API key
- Waits for gateway `/health/ready` before treating stack as usable (FR-UI-003)

Document unsupported UI features rather than simulating them (FR-UI-004).

## 5. Gateway Process

- Entry: `uvicorn gateway.main:app`
- Port: `8000`
- Logs: `mcp.log` when using `start.sh`
- No project Dockerfile for the gateway itself (UI-only Docker) — Gap for packaged release

## 6. Storage Layout

| Path / volume | Content |
|---|---|
| `MEMORY_SQLITE_URL` (default under `files/`) | Authoritative memory |
| `MEMORY_VECTOR_PATH` | Derived FAISS |
| Open WebUI volumes | UI state / HF cache |
| Temp media | Ephemeral; must clean up |

Protect permissions; exclude personal derived data from source control (SEC-013).

## 7. Data-Egress Map

When hosted NVIDIA APIs are used, the following may leave the machine:

- prompts and conversation messages;
- selected memory snippets;
- images, URLs, extracted frames/metadata;
- image gen/edit prompts and source images;
- provider auth/routing metadata.

Hybrid product: not offline/zero-egress. Link provider privacy terms when publishing (PRI-007 Gap).

## 8. Backup and Recovery (PRD §17.3)

- Back up relational memory and required Open WebUI state consistently.
- Keep config templates separate from secret material.
- Rebuild FAISS/pgvector from authoritative records via reindex.
- Validate schema compatibility before restore.
- Test corrupt index, interrupted migration, unavailable provider, lost queue (NFR-REL-006/007).

## 9. Upgrades

- Pin dependency lockfiles and UI digest for releases.
- Run migrations when DATA-001 is Implemented; do not rely on runtime `create_all` alone for production.
- Smoke readiness, models, chat, memory stats after upgrade.

## 10. Supported Matrix (Target)

Publish Linux-first matrix (OD-013): Python version, Docker versions, SQLite/FAISS defaults, optional Postgres/Redis, FFmpeg/yt-dlp when video enabled.

## 11. Related Documents

- `docs/operations/LOCAL_SETUP.md`
- `docs/operations/RELEASE_CHECKLIST.md`
- `docs/requirements/SECURITY_REQUIREMENTS.md`
- `docs/engineering/CONFIGURATION.md`
