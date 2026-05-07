import json
import httpx
import logging
from config import MODEL, BASE_URL, get_nvidia_api_key

logging.basicConfig(level=logging.INFO)


# =========================
# LLM CLIENT
# =========================
class LLMClient:
    def __init__(self):
        self.api_key = get_nvidia_api_key()

        if not self.api_key:
            raise RuntimeError("Missing NVIDIA API key")

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

    # =========================
    # STREAMING CORE
    # =========================
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

                # -------------------------
                # API ERROR HANDLING
                # -------------------------
                if res.status_code != 200:
                    err = await res.aread()
                    error_msg = f"[LLM_ERROR {res.status_code}] {err.decode()}"
                    logging.error(error_msg)
                    yield error_msg
                    return

                # -------------------------
                # STREAM PARSER
                # -------------------------
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

                        delta = (
                            obj.get("choices", [{}])[0]
                            .get("delta", {})
                        )

                        content = delta.get("content")

                        if content:
                            yield content

                    except json.JSONDecodeError:
                        continue

                    except Exception as e:
                        logging.warning(f"Stream parse error: {e}")
                        continue

        except httpx.RequestError as e:
            error_msg = f"[NETWORK_ERROR] {str(e)}"
            logging.error(error_msg)
            yield error_msg

        except Exception as e:
            error_msg = f"[LLM_EXCEPTION] {str(e)}"
            logging.error(error_msg)
            yield error_msg

    # =========================
    # CLEANUP
    # =========================
    async def close(self):
        await self.client.aclose()


# =========================
# SINGLETON INSTANCE
# =========================
llm_client = LLMClient()


# =========================
# PUBLIC STREAM API
# =========================
async def stream_llm(messages):
    async for token in llm_client.stream(messages):
        yield token