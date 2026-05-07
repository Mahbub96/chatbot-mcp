import inspect
from tools.file_tools import read_file, write_file, delete_file

TOOLS = {
    "read_file": read_file,
    "write_file": write_file,
    "delete_file": delete_file
}


def run_tool(name: str, args: dict):
    if name not in TOOLS:
        return {
            "success": False,
            "error": f"Tool not found: {name}"
        }

    tool = TOOLS[name]

    if not isinstance(args, dict):
        return {
            "success": False,
            "error": "Args must be a dictionary"
        }

    try:
        # Validate function signature
        sig = inspect.signature(tool)
        filtered_args = {
            k: v for k, v in args.items()
            if k in sig.parameters
        }

        result = tool(**filtered_args)

        return {
            "success": True,
            "tool": name,
            "result": result
        }

    except Exception as e:
        return {
            "success": False,
            "tool": name,
            "error": str(e)
        }