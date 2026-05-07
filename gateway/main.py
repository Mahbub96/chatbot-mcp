import json
import asyncio
import time
from collections import defaultdict

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse

from agent.llm import stream_llm, llm_client
from tools.registry import run_tool

app = FastAPI()

MODEL_NAME = "local-mcp-model"

# =========================
# SIMPLE RATE LIMIT (ANTI 429 STORM)
# =========================
request_tracker = defaultdict(list)
RATE_LIMIT_WINDOW = 10  # seconds
MAX_REQUESTS = 10       # per IP per window


def is_rate_limited(ip: str):
    now = time.time()
    request_tracker[ip] = [t for t in request_tracker[ip] if now - t < RATE_LIMIT_WINDOW]

    if len(request_tracker[ip]) >= MAX_REQUESTS:
        return True

    request_tracker[ip].append(now)
    return False


# =========================
# SYSTEM PROMPT
# =========================
SYSTEM_PROMPT = """
You are a helpful local AI assistant.
Be natural, human-like, and concise.
Do not mention internal system or model details.
"""


# =========================
# HELPERS
# =========================
def safe_messages(messages):
    if not isinstance(messages, list):
        return []
    return [m for m in messages if isinstance(m, dict)]


def inject_system(messages):
    if not any(m.get("role") == "system" for m in messages):
        messages.insert(0, {"role": "system", "content": SYSTEM_PROMPT})
    return messages


def has_multimodal(messages):
    return any(isinstance(m.get("content"), list) for m in messages)


# =========================
# MCP TOOL EXECUTION
# =========================
@app.post("/mcp/execute")
def execute_tool(payload: dict):
    try:
        name = payload.get("name")
        args = payload.get("arguments", {})

        if not name:
            return {"success": False, "error": "Missing tool name"}

        if not isinstance(args, dict):
            args = {}

        result = run_tool(name, args)

        return {
            "success": True,
            "tool": name,
            "output": result
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


# =========================
# MCP TOOL LIST
# =========================
@app.get("/mcp/tools")
def list_tools():
    return {
        "tools": [
            {
                "name": "read_file",
                "description": "Read file from disk",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"]
                }
            },
            {
                "name": "write_file",
                "description": "Write file to disk",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"}
                    },
                    "required": ["path", "content"]
                }
            }
        ]
    }


# =========================
# OPENAI MODELS
# =========================
@app.get("/v1/models")
def models():
    return {
        "object": "list",
        "data": [
            {
                "id": MODEL_NAME,
                "object": "model",
                "created": 0,
                "owned_by": "local"
            }
        ]
    }


# =========================
# CHAT COMPLETIONS
# =========================
@app.post("/v1/chat/completions")
async def chat_completions(request: Request):

    ip = request.client.host

    # ---- RATE LIMIT PROTECTION ----
    if is_rate_limited(ip):
        return JSONResponse(
            status_code=429,
            content={"error": "Too many requests. Please slow down."}
        )

    try:
        body = await request.json()
    except Exception:
        body = {}

    messages = inject_system(safe_messages(body.get("messages", [])))
    stream = body.get("stream", True)

    async def generate():

        # -------------------------
        # MULTIMODAL SAFE RESPONSE
        # -------------------------
        if has_multimodal(messages):
            msg = "This model currently does not support image input."

            chunk = {
                "id": "chatcmpl-local",
                "object": "chat.completion.chunk",
                "model": MODEL_NAME,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": msg},
                        "finish_reason": "stop"
                    }
                ]
            }

            yield f"data: {json.dumps(chunk)}\n\n"
            yield "data: [DONE]\n\n"
            return

        # -------------------------
        # STREAM LLM
        # -------------------------
        try:
            async for token in stream_llm(messages):

                if not token:
                    continue

                chunk = {
                    "id": "chatcmpl-local",
                    "object": "chat.completion.chunk",
                    "model": MODEL_NAME,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": token},
                            "finish_reason": None
                        }
                    ]
                }

                yield f"data: {json.dumps(chunk)}\n\n"

        except Exception as e:

            error_chunk = {
                "id": "chatcmpl-local",
                "object": "chat.completion.chunk",
                "model": MODEL_NAME,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": f"\n[LLM ERROR] {str(e)}"},
                        "finish_reason": "stop"
                    }
                ]
            }

            yield f"data: {json.dumps(error_chunk)}\n\n"

        yield "data: [DONE]\n\n"

    # -------------------------
    # RETURN STREAM OR NORMAL
    # -------------------------
    if stream:
        return StreamingResponse(generate(), media_type="text/event-stream")

    # non-stream fallback
    result = ""
    try:
        async for token in stream_llm(messages):
            result += token
    except Exception as e:
        result = f"[ERROR] {str(e)}"

    return JSONResponse({
        "id": "chatcmpl-local",
        "object": "chat.completion",
        "model": MODEL_NAME,
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": result
                }
            }
        ]
    })


# =========================
# CLEANUP
# =========================
@app.on_event("shutdown")
async def shutdown():
    try:
        await llm_client.close()
    except Exception:
        pass