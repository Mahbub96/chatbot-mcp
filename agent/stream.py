@app.post("/stream")
def stream(payload: dict):
    code = payload["code"]
    cursor = payload["cursor"]
    task = payload.get("task", "code")

    model = route_task(task)

    def event_generator():
        for token in stream_suggestions(code, cursor, model):
            yield f"data: {token}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")