import json
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse

from agent.llm import stream_llm, llm_client
from tools.registry import run_tool

app = FastAPI()

MODEL_NAME = "local-mcp-model"


# =========================
# SYSTEM PROMPT
# =========================
SYSTEM_PROMPT = """
You are a helpful local AI assistant.
Be natural, human-like, and concise.
You can help with coding, reasoning, and tool usage when needed.
Do not mention internal system details or architecture.
"""


# =========================
# SAFE HELPERS
# =========================
def safe_messages(messages):
    """Ensure messages are always valid list[dict]."""
    if not isinstance(messages, list):
        return []
    cleaned = []
    for m in messages:
        if isinstance(m, dict) and "role" in m:
            cleaned.append(m)
    return cleaned


def has_multimodal(messages):
    """Detect image / multimodal input safely."""
    for m in messages:
        content = m.get("content")
        if isinstance(content, list):
            return True
    return False


def ensure_system_prompt(messages):
    """Inject system prompt if missing."""
    if not any(m.get("role") == "system" for m in messages):
        messages.insert(0, {
            "role": "system",
            "content": SYSTEM_PROMPT
        })
    return messages


# =========================
# MCP TOOL EXECUTION
# =========================
@app.post("/mcp/execute")
def execute_tool(payload: dict):
    try:
        name = payload.get("name")
        args = payload.get("arguments", {})

        if not name:
            return {"success": False, "error": "Tool name missing"}

        if not isinstance(args, dict):
            args = {}

        result = run_tool(name, args)

        return {
            "success": True,
            "tool": name,
            "output": result
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


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
                    "properties": {
                        "path": {"type": "string"}
                    },
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
# OPENAI COMPAT: MODELS
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
                "owned_by": "local-mcp"
            }
        ]
    }


# =========================
# OPENAI COMPAT: CHAT
# =========================
@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}

    messages = safe_messages(body.get("messages", []))
    stream = body.get("stream", True)

    messages = ensure_system_prompt(messages)

    async def generate():

        # -------------------------
        # MULTIMODAL SAFE FALLBACK
        # -------------------------
        if has_multimodal(messages):
            msg = "This model does not support image input yet."

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
        # STREAM RESPONSE
        # -------------------------
        try:
            async for token in stream_llm(messages):

                if token is None:
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
            err = {
                "error": str(e)
            }

            chunk = {
                "id": "chatcmpl-local",
                "object": "chat.completion.chunk",
                "model": MODEL_NAME,
                "choices": [
                    {
                        "index": 0,
                        "delta": {"content": f"\n[ERROR] {err}"},
                        "finish_reason": "stop"
                    }
                ]
            }

            yield f"data: {json.dumps(chunk)}\n\n"

        yield "data: [DONE]\n\n"

    # -------------------------
    # STREAM OR NON-STREAM
    # -------------------------
    if stream:
        return StreamingResponse(generate(), media_type="text/event-stream")

    # fallback non-stream
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
# CLEAN SHUTDOWN
# =========================
@app.on_event("shutdown")
async def shutdown():
    try:
        await llm_client.close()
    except Exception:
        pass