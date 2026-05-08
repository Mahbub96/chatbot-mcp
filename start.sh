#!/bin/bash
set -e

echo "🚀 Starting FULL STACK (MCP + Open WebUI)..."

# =========================
# CONFIG
# =========================
WEBUI_PORT=3000
MCP_PORT=8000

CONTAINER_NAME="open-webui"
IMAGE="ghcr.io/open-webui/open-webui:main"

VOLUME_DATA="open-webui-data"
VOLUME_HF="hf-cache"

# =========================
# CLEANUP
# =========================
echo "🧹 Cleaning old services..."

docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true

# =========================
# DETECT MCP ENTRYPOINT
# =========================
if [ -f "gateway/main.py" ]; then
  MCP_APP="gateway.main:app"
elif [ -f "main.py" ]; then
  MCP_APP="main:app"
else
  echo "❌ Cannot find MCP entrypoint"
  exit 1
fi

echo "📡 MCP app: $MCP_APP"

# =========================
# START MCP
# =========================
echo "📡 Starting MCP server..."

export PYTHONPATH="$(pwd)"

uvicorn "$MCP_APP" \
  --host 0.0.0.0 \
  --port $MCP_PORT \
  > mcp.log 2>&1 &

MCP_PID=$!
echo "📌 MCP PID: $MCP_PID"

# =========================
# WAIT FOR MCP
# =========================
echo "⏳ Waiting for MCP API..."

for i in {1..40}; do
  if curl -fsS "http://127.0.0.1:$MCP_PORT/health/ready" >/dev/null 2>&1; then
    echo "✅ MCP is ready"
    break
  fi

  if ! kill -0 $MCP_PID >/dev/null 2>&1; then
    echo "❌ MCP crashed"
    tail -n 50 mcp.log
    exit 1
  fi

  echo "   waiting... ($i/40)"
  sleep 1
done

# =========================
# FINAL CHECK
# =========================
if ! curl -fsS "http://127.0.0.1:$MCP_PORT/health/ready" >/dev/null 2>&1; then
  echo "❌ MCP failed to start properly"
  python - <<'PY'
from pathlib import Path
log = Path("mcp.log")
if not log.exists():
    print("mcp.log not found")
else:
    text = log.read_text(encoding="utf-8", errors="ignore").splitlines()
    for line in text[-50:]:
        print(line)
PY
  exit 1
fi

# =========================
# VOLUMES
# =========================
docker volume inspect "$VOLUME_DATA" >/dev/null 2>&1 || docker volume create "$VOLUME_DATA"
docker volume inspect "$VOLUME_HF" >/dev/null 2>&1 || docker volume create "$VOLUME_HF"

# =========================
# START OPEN WEBUI (FIXED NETWORK)
# =========================
echo "📦 Starting Open WebUI..."

docker run -d \
  --name "$CONTAINER_NAME" \
  -p "$WEBUI_PORT:8080" \
  -v "$VOLUME_DATA:/app/backend/data" \
  -v "$VOLUME_HF:/root/.cache/huggingface" \
  -e HF_HOME=/root/.cache/huggingface \
  -e OPENAI_API_BASE_URL=http://host.docker.internal:$MCP_PORT/v1 \
  -e OPENAI_API_KEY=dummy \
  -e WEBUI_SECRET_KEY=$(openssl rand -hex 32) \
  --add-host=host.docker.internal:host-gateway \
  --restart unless-stopped \
  "$IMAGE"

# =========================
# DONE
# =========================
echo ""
echo "✅ SYSTEM READY"
echo "🌐 Open WebUI: http://localhost:$WEBUI_PORT"
echo "📡 MCP API: http://127.0.0.1:$MCP_PORT"
echo ""
echo "✔ Test:"
echo "   curl http://127.0.0.1:$MCP_PORT/v1/models"