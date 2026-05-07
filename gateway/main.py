import json
import asyncio
import time
import importlib
import pkgutil
from collections import defaultdict
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse

from agent.llm import stream_llm

app = FastAPI()

MODEL_NAME = "local-mcp-model"

# =========================
# RATE LIMIT
# =========================
request_tracker = defaultdict(list)
RATE_LIMIT_WINDOW = 100
MAX_REQUESTS = 100


def is_rate_limited(ip: str):
    now = time.time()
    request_tracker[ip] = [
        t for t in request_tracker[ip] if now - t < RATE_LIMIT_WINDOW
    ]

    if len(request_tracker[ip]) >= MAX_REQUESTS:
        return True

    request_tracker[ip].append(now)
    return False


# =========================
# SYSTEM PROMPT
# =========================
SYSTEM_PROMPT = """
You are a helpful local AI assistant.
You can use tools when needed.
Be concise and practical.
"""


def safe_messages(messages):
    return [m for m in messages if isinstance(m, dict)] if isinstance(messages, list) else []


def inject_system(messages):
    if not any(m.get("role") == "system" for m in messages):
        messages.insert(0, {"role": "system", "content": SYSTEM_PROMPT})
    return messages


def has_multimodal(messages):
    return any(isinstance(m.get("content"), list) for m in messages)


# =========================================================
# AUTO TOOL DISCOVERY (NO MANUAL REGISTRY)
# =========================================================
TOOLS = {}


def load_tools():
    """
    Automatically loads all tools from tools/ directory.
    Each tool file must expose:
        - tool_name (str)
        - run(**kwargs) function
    """
    tools_path = Path(__file__).resolve().parents[1] / "tools"

    for module_info in pkgutil.iter_modules([str(tools_path)]):
        if module_info.name.startswith("__"):
            continue

        module = importlib.import_module(f"tools.{module_info.name}")

        if hasattr(module, "tool_name") and hasattr(module, "run"):
            TOOLS[module.tool_name] = module.run


load_tools()


def run_tool(name: str, args: dict):
    if name not in TOOLS:
        return {"success": False, "error": f"Tool not found: {name}"}

    try:
        return TOOLS[name](**args)
    except Exception as e:
        return {"success": False, "error": str(e)}


# =========================
# MCP TOOL EXECUTION
# =========================
@app.post("/mcp/execute")
async def execute_tool(payload: dict):
    name = payload.get("name")
    args = payload.get("arguments", {})

    if not name:
        return {"success": False, "error": "Missing tool name"}

    return {
        "success": True,
        "tool": name,
        "result": run_tool(name, args or {})
    }


# =========================
# TOOL LIST (AUTO GENERATED)
# =========================
@app.get("/mcp/tools")
def list_tools():
    return {
        "tools": [
            {
                "name": name,
                "description": f"Auto-loaded tool: {name}",
                "parameters": {"type": "object"}
            }
            for name in TOOLS.keys()
        ]
    }


# =========================
# MODELS (OPEN WEBUI REQUIRED)
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

    if is_rate_limited(ip):
        return JSONResponse(status_code=429, content={"error": "Too many requests"})

    body = await request.json()
    messages = inject_system(safe_messages(body.get("messages", [])))
    stream = body.get("stream", True)

    async def generate():

        if has_multimodal(messages):
            yield f"data: {json.dumps({
                'id': 'error',
                'object': 'chat.completion.chunk',
                'model': MODEL_NAME,
                'choices': [{
                    'index': 0,
                    'delta': {'content': 'Image input not supported.'},
                    'finish_reason': 'stop'
                }]
            })}\n\n"
            yield "data: [DONE]\n\n"
            return

        # =========================
        # TOOL CALL (LLM CONTROLLED LATER)
        # =========================
        user_msg = messages[-1]["content"] if messages else ""

        tool_output = None

        if "read file" in user_msg.lower():
            tool_output = run_tool("read_file", {"path": "test.txt"})

        elif "write file" in user_msg.lower():
            tool_output = run_tool("write_file", {
                "path": "test.txt",
                "content": user_msg
            })

        elif "delete file" in user_msg.lower():
            tool_output = run_tool("delete_file", {"path": "test.txt"})

        if tool_output:
            yield f"data: {json.dumps({
                'id': 'tool',
                'object': 'chat.completion.chunk',
                'model': MODEL_NAME,
                'choices': [{
                    'index': 0,
                    'delta': {
                        'content': f"\n[TOOL RESULT]\n{json.dumps(tool_output)}\n"
                    },
                    'finish_reason': None
                }]
            })}\n\n"

        # =========================
        # STREAM LLM
        # =========================
        try:
            async for token in stream_llm(messages):
                if not token:
                    continue

                yield f"data: {json.dumps({
                    'id': 'chatcmpl-local',
                    'object': 'chat.completion.chunk',
                    'model': MODEL_NAME,
                    'choices': [{
                        'index': 0,
                        'delta': {'content': token},
                        'finish_reason': None
                    }]
                })}\n\n"

        except Exception as e:
            yield f"data: {json.dumps({
                'id': 'error',
                'object': 'chat.completion.chunk',
                'model': MODEL_NAME,
                'choices': [{
                    'index': 0,
                    'delta': {'content': f'[ERROR] {str(e)}'},
                    'finish_reason': 'stop'
                }]
            })}\n\n"

        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


# =========================
# SHUTDOWN
# =========================
@app.on_event("shutdown")
async def shutdown():
    pass