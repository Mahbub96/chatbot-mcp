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
- Persistent memory (MVP):
  - Vector retrieval via FAISS
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
- **`BANGLA_MODEL`**: optional upstream model id for Bangla routing.
- **`CODE_MODEL`**: optional upstream model id for coding-focused prompts.
- **`VISION_MODEL`**: optional vision-capable model id for image inputs.
  - If image input is sent and `VISION_MODEL` is empty, gateway returns a clear config error.
- **`IMAGE_GEN_MODEL`**: text-to-image generation model id (recommended: `qwen/qwen-image`).
- **`IMAGE_EDIT_MODEL`**: image editing model id (recommended: `qwen/qwen-image-edit`).
- **`MEMORY_ENABLED`**: enables memory retrieval/storage in chat flow.
- **`MEMORY_SQLITE_URL`**: SQLAlchemy database URL for memory records.
- **`MEMORY_VECTOR_PATH`**: persistent folder path for FAISS vector index.
- **`MEMORY_TOP_K`**: number of memory items retrieved per request.
- **`MEMORY_MIN_SCORE`**: retrieval score threshold for injected memory.
- **`MEMORY_AUTO_STORE`**: whether chat user turns are auto-stored.
- **`MEMORY_MAX_ITEMS`**: cap per memory scope before pruning oldest records.

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

## Quick API checks

```bash
# list model exposed to WebUI
curl http://127.0.0.1:8000/v1/models

# list local MCP tools
curl http://127.0.0.1:8000/mcp/tools
```

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
- The gateway accepts both:
  - publicly reachable image URLs
  - base64 data URLs (for example uploads from chat UI)
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
