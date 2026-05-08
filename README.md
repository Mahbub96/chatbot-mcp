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
  - Image/multimodal requests -> `VISION_MODEL` (if set)
  - Fallback -> `DEFAULT_MODEL`

---

# 🏗️ Architecture

This stack has two parts:

- **Gateway (FastAPI)**: [`gateway/main.py`](gateway/main.py)
  - OpenAI-compatible endpoints:
    - `GET /v1/models`
    - `POST /v1/chat/completions` (stream + non-stream)
  - MCP-style endpoints:
    - `GET /mcp/tools`
    - `POST /mcp/execute`
  - **Routing**:
    - Bangla text -> `BANGLA_MODEL` (if set)
    - Image input -> `VISION_MODEL` (if set)
    - Otherwise -> `DEFAULT_MODEL`
- **Open WebUI (Docker)**: started by [`start.sh`](start.sh) and configured to talk to the gateway.

Tooling:
- Tools live in [`tools/`](tools/) and are auto-discovered by [`tools/registry.py`](tools/registry.py).
- Current example tool: [`tools/file_tools.py`](tools/file_tools.py) (safe file read/write/list/delete under `files/`).

## Environment variables

- **`NVIDIA_API_KEY`**: required for NVIDIA hosted NIM.
- **`DEFAULT_MODEL`**: upstream model id for normal (non-Bangla) routing.
- **`BANGLA_MODEL`**: optional upstream model id for Bangla routing.
- **`VISION_MODEL`**: optional vision-capable model id for image inputs.
  - If image input is sent and `VISION_MODEL` is empty, gateway returns a clear config error.

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
