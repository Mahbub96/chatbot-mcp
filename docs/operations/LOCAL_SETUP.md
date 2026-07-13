# Hybrid AI Gateway — Local Setup

Version: 1.0

Last reviewed: 13 July 2026

Status: first-run companion for trusted local development; see `DEPLOYMENT.md` for profiles and egress

## 1. Purpose

Get a single developer from clone to first successful chat on loopback with Open WebUI.

Authorities: PRD §6.1; FR-GWY-*; FR-UI-*; `README.md`; `start.sh`; `CONFIGURATION.md`.

## 2. Prerequisites

| Component | Notes |
|---|---|
| Python | Project-supported version; install deps from `requirements.txt` |
| Docker | Required for Open WebUI container |
| NVIDIA API key | Required for hosted inference |
| Disk | Space for SQLite, FAISS, Docker volumes, temp media |
| Optional | FFmpeg, yt-dlp (video); Redis/Postgres for non-default profiles |

**Target:** preflight matrix (FR-GWY-006). **Gap:** automated preflight not complete.

## 3. First-Run Steps

1. Clone repository; create Python environment.
2. Copy `.env.example` → `.env`; set `NVIDIA_API_KEY` and review models/memory settings.
3. Install: `pip install -r requirements.txt`.
4. Start stack: `bash start.sh` (or documented uvicorn + UI alternative).
5. Confirm gateway readiness before using UI (`start.sh` waits on `/health/ready`).
6. Open WebUI at `http://localhost:3000`; API at `http://127.0.0.1:8000`.
7. Smoke: model list, non-stream chat, stream chat — avoid sensitive tools until approvals understood.

## 4. Default Local Profile (OD-011)

| Concern | Default |
|---|---|
| Memory DB | SQLite under `files/` |
| Vectors | FAISS |
| Queue | In-process |
| Bind | **Implemented:** `start.sh` uses `0.0.0.0:8000` — **Gap** vs FR-GWY-001 loopback Target |
| UI | Docker `ghcr.io/open-webui/open-webui:main` on host port 3000 |

Treat non-loopback bind as unsafe without auth (SEC-002/004). Prefer accessing via `127.0.0.1` and plan loopback enforcement in Phase 0.

## 5. Optional RQ Worker

When `MEMORY_QUEUE_BACKEND=rq`:

```bash
python gateway/rq_worker.py
```

Requires Redis (`MEMORY_REDIS_URL`). Readiness should reflect queue health when that profile is required.

## 6. Short-Term Memory Dev Default

`.env.example` may set `SHORT_TERM_CLEAR_ON_RESTART=true` for clean restarts. Production Target is `false` with TTL retention (`CONFIGURATION.md`, FR-MEM-010).

## 7. Quick Checks

```bash
curl -s http://127.0.0.1:8000/health/live
curl -s http://127.0.0.1:8000/health/ready
curl -s http://127.0.0.1:8000/v1/models
curl -s http://127.0.0.1:8000/metrics | head
```

## 8. Related Documents

- `docs/operations/DEPLOYMENT.md`
- `docs/operations/TROUBLESHOOTING.md`
- `docs/engineering/CONFIGURATION.md`
- `README.md`
