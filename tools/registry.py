import inspect
import importlib
import pkgutil
from pathlib import Path
from typing import Any, Callable

import logging

logger = logging.getLogger(__name__)

# =========================
# TOOL STORE
# =========================
TOOLS: dict[str, Callable[..., Any]] = {}


# =========================
# AUTO DISCOVERY LOADER
# =========================
def load_tools():
    """
    Automatically loads all tools inside /tools directory.

    Each tool must expose:
        - tool_name (str)
        - run(**kwargs) function
    """

    tools_path = Path(__file__).resolve().parent

    for module_info in pkgutil.iter_modules([str(tools_path)]):

        if module_info.name.startswith("__"):
            continue

        module = importlib.import_module(f"tools.{module_info.name}")

        if hasattr(module, "tool_name") and hasattr(module, "run"):
            TOOLS[module.tool_name] = module.run
            logger.info("[TOOL LOADED] %s", module.tool_name)


# load at import time
load_tools()


# =========================
# TOOL EXECUTOR
# =========================
def run_tool(name: str, args: dict):
    """
    Safe execution layer for MCP tools
    """

    tool = TOOLS.get(name)

    if not tool:
        return {
            "success": False,
            "error": f"Tool not found: {name}",
            "available_tools": list(TOOLS.keys())
        }

    if not isinstance(args, dict):
        return {
            "success": False,
            "error": "Args must be a dictionary"
        }

    try:
        sig = inspect.signature(tool)

        has_varkw = any(
            p.kind == inspect.Parameter.VAR_KEYWORD
            for p in sig.parameters.values()
        )

        # -------------------------
        # REQUIRED PARAM CHECK
        # -------------------------
        missing = [
            p_name
            for p_name, p in sig.parameters.items()
            if (
                p.kind != inspect.Parameter.VAR_KEYWORD
                and p.default == inspect._empty
                and p_name not in args
            )
        ]

        if missing:
            return {
                "success": False,
                "tool": name,
                "error": f"Missing required args: {missing}"
            }

        # -------------------------
        # ARG FILTERING
        # -------------------------
        # If the tool accepts **kwargs, pass args through unfiltered.
        # Otherwise, keep only explicitly declared parameters.
        if has_varkw:
            filtered_args = args
        else:
            filtered_args = {k: v for k, v in args.items() if k in sig.parameters}

        logger.info("[TOOL] %s | args=%s", name, filtered_args)

        result = tool(**filtered_args)

        return {
            "success": True,
            "tool": name,
            "args": filtered_args,
            "result": result
        }

    except Exception as e:
        logger.exception("[TOOL ERROR] %s", name)

        return {
            "success": False,
            "tool": name,
            "error": str(e)
        }
        