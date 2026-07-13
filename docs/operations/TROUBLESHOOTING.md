# Hybrid AI Gateway — Troubleshooting

Version: 1.0

Last reviewed: 13 July 2026

Status: operator failure playbook mapped to health/metrics and pipeline degraded behavior

## 1. Purpose

Classify failure origin and apply the smallest diagnostic path.

Authorities: FR-CHAT-005; FR-GWY-003; FR-MOD-004; `AI_PIPELINE.md` §15; `ERROR_HANDLING.md`; `OBSERVABILITY.md`.

## 2. First Checks

```bash
curl -s http://127.0.0.1:8000/health/live
curl -s http://127.0.0.1:8000/health/ready
curl -s http://127.0.0.1:8000/health/routes
tail -n 100 mcp.log
```

Inspect `/metrics` for path/status spikes. Confirm `.env` has `NVIDIA_API_KEY` and expected models.

## 3. Failure Origin Taxonomy

| Origin | Symptoms | Actions |
|---|---|---|
| Gateway not ready | `/health/ready` 503 | Check key, memory backend, missing routes, crash in `mcp.log` |
| Configuration | Vision/image/model errors | Set models; see FR-GWY-004 / CONFIGURATION |
| Provider | 502 / timeout / rate limit | Distinguish invalid key, quota, model unavailable, 5xx; do not treat as user validation |
| Memory | Empty recall / index errors | Check scope, `MEMORY_ENABLED`, reindex, SQLite path, FAISS dim mismatch |
| Queue | Jobs stuck | Check `MEMORY_QUEUE_BACKEND`, Redis, RQ worker |
| Media | Fetch/decode failures | Size limits, URL policy, FFmpeg/yt-dlp presence |
| Tools | `requires_approval` / deny | Use `/mcp/approvals` and `/mcp/approve`; check policy |
| Client / UI | WebUI cannot reach API | Docker host gateway URL; wait for ready; port 3000/8000 |

## 4. Provider Failures

Map to stable codes (Target taxonomy). Common cases:

- Invalid / missing API key → configuration/provider unauthorized
- Rate limit → 429 / provider_rate_limited
- Model retired or denied → operator diagnostic (FR-MOD-004), not “bad prompt”
- Timeout → bounded failure; retry only if safe

## 5. Memory and Index Recovery

| Condition | Behavior |
|---|---|
| Vector corrupt / dim mismatch | Degrade to structured/FTS; reindex guidance (NFR-REL-003) |
| Embedding failure | Keep relational fact (AI-PIPE-014) |
| Short-term cleared on restart | Expected if `SHORT_TERM_CLEAR_ON_RESTART=true` (dev) |
| Cross-scope miss | By design; do not enable unsafe any-scope fallback for personal facts |

## 6. Pipeline Degraded Matrix (Summary)

From `AI_PIPELINE.md` §15: STT unavailable → reject speech only; long-term failure → answer continues; search disabled → explain local-only; no reliable evidence → explicit not-found; TTS failure → text preserved.

## 7. Tool / Approval States

Do not assume success from approval alone. States: approval-required, approved, denied, executing, succeeded, failed (`TOOL_PERMISSION_MODEL.md`). Process restart loses in-memory approvals (Gap).

## 8. Related Documents

- `docs/engineering/ERROR_HANDLING.md`
- `docs/engineering/OBSERVABILITY.md`
- `docs/operations/LOCAL_SETUP.md`
- `docs/architecture/AI_PIPELINE.md`
