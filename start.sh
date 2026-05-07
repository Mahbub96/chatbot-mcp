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
# CLEAN
# =========================
echo "🧹 Cleaning old services..."

pkill -f "uvicorn" >/dev/null 2>&1 || true
docker rm -f $CONTAINER_NAME >/dev/null 2>&1 || true

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

echo "📡 Using MCP app: $MCP_APP"

# =========================
# START MCP (FIXED)
# =========================
echo "📡 Starting MCP server..."

export PYTHONPATH="$(pwd)"

uvicorn $MCP_APP \
  --host 0.0.0.0 \
  --port $MCP_PORT \
  > mcp.log 2>&1 &

MCP_PID=$!
echo "📌 MCP PID: $MCP_PID"

# =========================
# WAIT FOR MCP (FIXED CHECK)
# =========================
echo "⏳ Waiting for MCP API..."

for i in {1..40}; do

  # generic health check (SAFE)
  if curl -s http://127.0.0.1:$MCP_PORT/ >/dev/null 2>&1; then
    echo "✅ MCP is responding"
    break
  fi

  # process check
  if ! kill -0 $MCP_PID >/dev/null 2>&1; then
    echo "❌ MCP crashed"
    tail -n 50 mcp.log
    exit 1
  fi

  echo "   waiting... ($i/40)"
  sleep 1
done

# FINAL HARD CHECK
if ! kill -0 $MCP_PID >/dev/null 2>&1; then
  echo "❌ MCP failed"
  tail -n 50 mcp.log
  exit 1
fi

# =========================
# VOLUMES
# =========================
docker volume inspect $VOLUME_DATA >/dev/null 2>&1 || docker volume create $VOLUME_DATA
docker volume inspect $VOLUME_HF >/dev/null 2>&1 || docker volume create $VOLUME_HF

# =========================
# START OPEN WEBUI
# =========================
echo "📦 Starting Open WebUI..."

docker run -d \
  --name $CONTAINER_NAME \
  -p $WEBUI_PORT:8080 \
  -v $VOLUME_DATA:/app/backend/data \
  -v $VOLUME_HF:/root/.cache/huggingface \
  -e HF_HOME=/root/.cache/huggingface \
  -e OPENAI_API_BASE_URL=http://host.docker.internal:$MCP_PORT/v1 \
  -e OPENAI_API_KEY=dummy \
  -e WEBUI_SECRET_KEY=$(openssl rand -hex 32) \
  --add-host=host.docker.internal:host-gateway \
  --restart unless-stopped \
  $IMAGE

# =========================
# DONE
# =========================
echo ""
echo "✅ SYSTEM READY"
echo "🌐 Open WebUI: http://localhost:$WEBUI_PORT"
echo "📡 MCP API: http://127.0.0.1:$MCP_PORT"
echo ""
echo "✔ Debug MCP:"
echo "   curl http://127.0.0.1:$MCP_PORT"
echo ""
echo "📄 Logs:"
echo "   tail -f mcp.log"