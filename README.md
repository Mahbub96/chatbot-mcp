# 🚀 Local MCP + Open WebUI Full Stack

This project runs a local chat stack with:

- ⚡ MCP (FastAPI-based model server)
- 🧠 Open WebUI (modern chat interface)
- 🐳 Docker-based deployment for UI
- 🔁 Single-command startup script

---

# 📦 Features

- One-command full stack startup
- Auto MCP server detection (`main` or `gateway`)
- Open WebUI integration via OpenAI-compatible API
- Persistent Docker volumes (faster restarts)
- Auto cleanup of previous processes
- Safe process monitoring (no silent failures)
- HuggingFace cache persistence
- NVIDIA hosted NIM upstream via `NVIDIA_API_KEY`
- Model routing support:
  - Bangla text -> `BANGLA_MODEL` (if set)
  - Code-heavy prompts -> `CODE_MODEL` (if set)
  - Image/multimodal requests -> `VISION_MODEL` (if set)
  - Fallback -> `DEFAULT_MODEL`
- Persistent memory (MVP/production-ready path):
  - Vector retrieval via FAISS or pgvector (HNSW)
  - Durable records via SQLite + SQLAlchemy ORM
  - Memory-augmented chat responses

---

# 🏗️ Architecture

This stack has two parts:

- **Gateway (FastAPI)**: [`gateway/main.py`](gateway/main.py)
  - OpenAI-compatible endpoints:
    - `GET /v1/models`
    - `POST /v1/chat/completions` (stream + non-stream)
    - `POST /v1/images/generations` (text-to-image)
    - `POST /v1/images/edits` (image editing)
  - MCP-style endpoints:
    - `GET /mcp/tools`
    - `POST /mcp/execute`
    - `GET /mcp/approvals`
    - `POST /mcp/approve`
  - **Routing**:
    - Bangla text -> `BANGLA_MODEL` (if set)
    - Code-heavy prompts -> `CODE_MODEL` (if set)
    - Image input -> `VISION_MODEL` (if set)
    - Otherwise -> `DEFAULT_MODEL`
- **Open WebUI (Docker)**: started by [`start.sh`](start.sh) and configured to talk to the gateway.

Tooling:
- Tools live in [`tools/`](tools/) and are auto-discovered by [`tools/registry.py`](tools/registry.py).
- Current example tool: [`tools/file_tools.py`](tools/file_tools.py) (safe file read/write/list/delete under `files/`).
- Shell command tool: [`tools/shell_tool.py`](tools/shell_tool.py) (approval required).

## Environment variables

- **`NVIDIA_API_KEY`**: required for NVIDIA hosted NIM.
- **`DEFAULT_MODEL`**: upstream model id for normal (non-Bangla) routing.
- **`EMBEDDING_BASE_URL`**: embeddings endpoint URL (OpenAI-compatible).
- **`EMBEDDING_MODEL`**: model id used for real memory embeddings.
- **`EMBEDDING_DIM`**: embedding dimensionality used by local vector index.
- **`EMBEDDING_TIMEOUT_SECONDS`**: timeout for embedding HTTP calls.
- **`BANGLA_MODEL`**: optional upstream model id for Bangla routing.
- **`CODE_MODEL`**: optional upstream model id for coding-focused prompts.
- **`VISION_MODEL`**: optional vision-capable model id for image inputs.
  - If image input is sent and `VISION_MODEL` is empty, gateway returns a clear config error.
- **`IMAGE_GEN_MODEL`**: text-to-image generation model id (recommended: `qwen/qwen-image`).
- **`IMAGE_EDIT_MODEL`**: image editing model id (recommended: `qwen/qwen-image-edit`).
- **`MEMORY_ENABLED`**: enables memory retrieval/storage in chat flow.
- **`MEMORY_SQLITE_URL`**: SQLAlchemy database URL for memory records.
- **`MEMORY_VECTOR_PATH`**: persistent folder path for FAISS vector index.
- **`MEMORY_VECTOR_BACKEND`**: vector backend (`faiss` or `pgvector`).
- **`MEMORY_TOP_K`**: number of memory items retrieved per request.
- **`MEMORY_MIN_SCORE`**: retrieval score threshold for injected memory.
- **`PGVECTOR_HNSW_M`**: pgvector HNSW graph connectivity parameter.
- **`PGVECTOR_HNSW_EF_CONSTRUCTION`**: pgvector HNSW build-time recall/speed parameter.
- **`MEMORY_AUTO_STORE`**: whether chat user turns are auto-stored.
- **`MEMORY_MAX_ITEMS`**: cap per memory scope before pruning oldest records.
- **`SHORT_TERM_TRACE_MAX_ITEMS`**: cap per scope for chat trace rows.
- **`MEMORY_QUEUE_BACKEND`**: memory async backend (`inprocess` or `rq`).
- **`MEMORY_REDIS_URL`**: Redis connection URL used by RQ.
- **`MEMORY_RQ_QUEUE`**: RQ queue name for memory jobs.
- **`RATE_LIMIT_WINDOW_SECONDS`**: global rate-limit window size in seconds.
- **`RATE_LIMIT_MAX_REQUESTS`**: max requests per client IP within the window.
- **`LOG_JSON`**: enable structured JSON request logs.
- **`VISION_STREAM_TIMEOUT_SECONDS`**: max time to wait for vision response in streamed chat before timeout error.

Use `.env.example` as template:

```bash
cp .env.example .env
```

## Run

```bash
pip install -r requirements.txt
bash start.sh
```

Open WebUI: `http://localhost:3000`  
Gateway API: `http://127.0.0.1:8000`

### Optional: run external RQ memory worker (production)

When `MEMORY_QUEUE_BACKEND=rq`, chat requests enqueue memory jobs into Redis and a separate worker processes them:

```bash
python gateway/rq_worker.py
```

If Redis or RQ is unavailable, the gateway safely falls back to in-process background queueing.

## Quick API checks

```bash
# list model exposed to WebUI
curl http://127.0.0.1:8000/v1/models

# list local MCP tools
curl http://127.0.0.1:8000/mcp/tools

# liveness/readiness probes
curl http://127.0.0.1:8000/health/live
curl http://127.0.0.1:8000/health/ready

# prometheus metrics
curl http://127.0.0.1:8000/metrics
```

## Operations

- Health probes:
  - `GET /health/live` returns process liveness.
  - `GET /health/ready` returns readiness; responds `503` when dependencies are unavailable.
- Metrics:
  - `GET /metrics` exposes Prometheus text metrics for request counts and latency sum.
- Request tracing:
  - Every response includes `X-Request-Id` and `X-Process-Time-Ms`.
  - When `LOG_JSON=true`, middleware emits structured per-request logs.
- Graceful shutdown:
  - On shutdown, the gateway closes upstream async HTTP clients to avoid leaked connections.

## Hybrid Retrieval Pipeline

```text
Client -> /chat or /v1/chat/completions
      -> Model Router (vision/code/bangla/default)
      -> Fast Path (LLM response, stream/non-stream)
      -> Optional Memory Retrieval (ANN HNSW -> metadata filter -> FTS fallback)
      -> Response to client (<1s target for text-only)
      -> Async Memory Queue (background worker)
           -> importance/category classifier
           -> durable write (SQLite/Postgres-compatible schema)
           -> FAISS HNSW index update
```

- **Fast path** keeps user-visible latency low by avoiding blocking memory writes.
- **Async path** classifies and stores only useful facts (`person`, `education`, `work`, `preference`, `event`, `contact`).
- **Fallback retrieval** uses lexical/FTS search if ANN similarity misses.
- **Vector backend switch** keeps the same app API while allowing:
  - local `faiss` for simple setups
  - `pgvector` on PostgreSQL for production HNSW ANN

## Cursor AI integration (both)

You can integrate this project with Cursor in two ways:

1) **Cursor Agent tools via MCP** (recommended for actions)
2) **Chat/model endpoint via OpenAI-compatible API** (`/v1/chat/completions`)

### 1) MCP tools in Cursor

This repo includes a bridge server: [`cursor_mcp_server.py`](cursor_mcp_server.py).  
It forwards Cursor MCP tool calls to your local gateway (`/mcp/*`) and preserves approval flow.

Add an MCP server in Cursor pointing to:

- Command: `python`
- Args: `["cursor_mcp_server.py"]`
- Working directory: project root
- Env:
  - `GATEWAY_URL=http://127.0.0.1:8000`

Exposed MCP tools:
- `gateway_health`
- `list_gateway_tools`
- `execute_gateway_tool`
- `list_pending_approvals`
- `approve_gateway_action`

### 2) Chat endpoint in Cursor

Use Cursor's OpenAI-compatible model/provider settings with:

- Base URL: `http://127.0.0.1:8000/v1`
- API key: any non-empty value (gateway ignores it currently)
- Model id: `local-mcp-model`

Then Cursor chat requests are served by your gateway, which applies routing:
- image -> `VISION_MODEL`
- code intent -> `CODE_MODEL`
- Bangla text -> `BANGLA_MODEL`
- fallback -> `DEFAULT_MODEL`

For text-to-image generation, use `/v1/images/generations` with `IMAGE_GEN_MODEL`.
For image editing, use `/v1/images/edits` with `IMAGE_EDIT_MODEL`.

## Image input behavior (important)

- Image explanation in chat is supported through `POST /v1/chat/completions`.
- The gateway requires publicly reachable `http/https` image URLs.
- Inline base64 image data URLs and private/local URLs are rejected with clear `400` errors.
- For stability with some upstream vision models, the gateway uses a non-stream upstream call for image requests and then returns the result to clients (including SSE clients).
- Image requests can be slower than text-only requests (often much longer first-token latency depending on model/provider load).

## Approval workflow

Sensitive actions require explicit approval (for example `shell_command`, file write/delete):

```bash
# 1) request action (returns approval_id)
curl -X POST http://127.0.0.1:8000/mcp/execute \
  -H "content-type: application/json" \
  -d '{"name":"shell_command","arguments":{"command":"ls -la"}}'

# 2) approve or reject
curl -X POST http://127.0.0.1:8000/mcp/approve \
  -H "content-type: application/json" \
  -d '{"approval_id":"<id>","approved":true}'

# 3) execute with approval_id
curl -X POST http://127.0.0.1:8000/mcp/execute \
  -H "content-type: application/json" \
  -d '{"name":"shell_command","arguments":{"command":"ls -la"},"approval_id":"<id>"}'
```

## Memory API (MVP)

```bash
# add memory item
curl -X POST http://127.0.0.1:8000/memory/items \
  -H "content-type: application/json" \
  -d '{"memory_scope":"global","text":"My name is Mahbub","source":"manual","importance":0.9}'

# search memory
curl -X POST http://127.0.0.1:8000/memory/search \
  -H "content-type: application/json" \
  -d '{"memory_scope":"global","query":"what is my name?","limit":5}'

# list memory items
curl "http://127.0.0.1:8000/memory/items?memory_scope=global&limit=20"

# reindex scope from SQLite -> FAISS
curl -X POST http://127.0.0.1:8000/memory/reindex \
  -H "content-type: application/json" \
  -d '{"memory_scope":"global"}'
```

## Common errors

- `401 Unauthorized`:
  - Usually invalid `NVIDIA_API_KEY`.
  - Fix key in `.env`, restart gateway.
- `429 Too Many Requests`:
  - Upstream NIM rate limit hit.
  - Retry later, reduce request rate, or change model/account quota.
- `410 Gone` for a model:
  - Model reached end-of-life on provider side.
  - Switch to another available model id.
- `404 Not Found` on `/v1/images/generations`:
  - The configured `IMAGE_GEN_MODEL` or `IMAGE_BASE_URL` is not available for your NVIDIA account.
  - Use a model/endpoint pair that is enabled for your key.
- Vision/image explanation timeout or `[NETWORK_ERROR] ReadTimeout`:
  - Vision requests may need significantly longer processing time than text-only requests.
  - Retry once; if persistent, try a different vision model or reduce image size/input complexity.
