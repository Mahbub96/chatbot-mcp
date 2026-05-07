import inspect
import logging
import importlib
import pkgutil
from pathlib import Path

logging.basicConfig(level=logging.INFO)

# =========================
# TOOL STORE
# =========================
TOOLS = {}


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
            logging.info(f"[TOOL LOADED] {module.tool_name}")


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

        # -------------------------
        # REQUIRED PARAM CHECK
        # -------------------------
        missing = [
            p_name
            for p_name, p in sig.parameters.items()
            if p.default == inspect._empty and p_name not in args
        ]

        if missing:
            return {
                "success": False,
                "tool": name,
                "error": f"Missing required args: {missing}"
            }

        # -------------------------
        # STRICT FILTER (NO EXTRA ARGS)
        # -------------------------
        filtered_args = {
            k: v for k, v in args.items()
            if k in sig.parameters
        }

        logging.info(f"[TOOL] {name} | args={filtered_args}")

        result = tool(**filtered_args)

        return {
            "success": True,
            "tool": name,
            "args": filtered_args,
            "result": result
        }

    except Exception as e:
        logging.exception(f"[TOOL ERROR] {name}")

        return {
            "success": False,
            "tool": name,
            "error": str(e)
        }
        