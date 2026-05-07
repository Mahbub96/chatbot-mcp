# agent/context.py

def build_context(file_content: str, cursor: int, window: int = 40):
    lines = file_content.split("\n")

    start = max(0, cursor - window)
    end = min(len(lines), cursor + window)

    return "\n".join(lines[start:end])


def build_messages(user_input: str, system: str = None):
    messages = []

    if system:
        messages.append({"role": "system", "content": system})

    messages.append({"role": "user", "content": user_input})

    return messages