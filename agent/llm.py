import json
import httpx
from config import MODEL, BASE_URL, get_nvidia_api_key


class LLMClient:
    def __init__(self):
        self.api_key = get_nvidia_api_key()

        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0),
            limits=httpx.Limits(
                max_connections=50,
                max_keepalive_connections=20,
            ),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

    async def stream(self, messages):
        payload = {
            "model": MODEL,
            "messages": messages,
            "stream": True,
            "temperature": 0.7,
        }

        try:
            async with self.client.stream(
                "POST",
                BASE_URL,
                json=payload
            ) as res:

                # handle API errors cleanly
                if res.status_code != 200:
                    text = await res.aread()
                    yield f"[LLM_ERROR]: {text.decode()}"
                    return

                async for line in res.aiter_lines():
                    if not line:
                        continue

                    if not line.startswith("data:"):
                        continue

                    data = line[5:].strip()

                    if data == "[DONE]":
                        break

                    try:
                        obj = json.loads(data)
                        delta = obj["choices"][0].get("delta", {})
                        content = delta.get("content")

                        if content:
                            yield content

                    except Exception:
                        continue

        except Exception as e:
            yield f"[LLM_EXCEPTION]: {str(e)}"

    async def close(self):
        await self.client.aclose()


# Singleton (safe lazy init)
llm_client = LLMClient()


def stream_llm(messages):
    return llm_client.stream(messages)