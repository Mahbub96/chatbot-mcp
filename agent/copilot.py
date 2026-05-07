from agent.llm import stream_llm

def build_prompt(code, cursor_line):
    return [
        {
            "role": "system",
            "content": "You are a Copilot-style inline code completion engine."
        },
        {
            "role": "user",
            "content": f"""
Complete ONLY the code from cursor position.

CODE:
{code}

Return only continuation.
"""
        }
    ]


def stream_suggestions(code, cursor_line):
    messages = build_prompt(code, cursor_line)

    for chunk in stream_llm(messages):
        yield chunk