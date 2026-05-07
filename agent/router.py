def route_task(task_type: str):
    if task_type == "chat":
        return "gemini"
    elif task_type == "code":
        return "deepseek_or_coder_model"
    elif task_type == "image":
        return "image_model"
    else:
        return "fast_llm"

def route_from_messages(messages):
    last = messages[-1]["content"]

    if "def " in last or "code" in last:
        return "code"
    elif "image" in last:
        return "image"
    else:
        return "chat"