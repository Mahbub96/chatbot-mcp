import json
import httpx
import logging
from config import (
    BASE_URL,
    IMAGE_BASE_URL,
    IMAGE_EDIT_BASE_URL,
    IMAGE_EDIT_MODEL,
    IMAGE_GEN_MODEL,
    MODEL,
    get_nvidia_api_key,
)

logging.basicConfig(level=logging.INFO)

DEFAULT_CONNECT_TIMEOUT = 20.0
DEFAULT_WRITE_TIMEOUT = 20.0
DEFAULT_POOL_TIMEOUT = 20.0
TEXT_READ_TIMEOUT = 60.0
VISION_READ_TIMEOUT = 180.0


def _contains_image_payload(messages) -> bool:
    if not isinstance(messages, list):
        return False
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if isinstance(part, dict) and part.get("type") == "image_url":
                return True
    return False


# =========================
# LLM CLIENT
# =========================
class LLMClient:
    def __init__(self):
        self.api_key = get_nvidia_api_key()

        if not self.api_key:
            raise RuntimeError("Missing NVIDIA API key")

        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=DEFAULT_CONNECT_TIMEOUT,
                read=TEXT_READ_TIMEOUT,
                write=DEFAULT_WRITE_TIMEOUT,
                pool=DEFAULT_POOL_TIMEOUT,
            ),
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
    async def stream(self, messages, model: str | None = None):
        is_image_request = _contains_image_payload(messages)
        payload = {
            "model": model or MODEL,
            "messages": messages,
            "stream": not is_image_request,
            "temperature": 0.7,
        }
        read_timeout = VISION_READ_TIMEOUT if is_image_request else TEXT_READ_TIMEOUT

        try:
            timeout = httpx.Timeout(
                connect=DEFAULT_CONNECT_TIMEOUT,
                read=read_timeout,
                write=DEFAULT_WRITE_TIMEOUT,
                pool=DEFAULT_POOL_TIMEOUT,
            )

            # Vision requests are more reliable via non-stream completion on this upstream path.
            if is_image_request:
                res = await self.client.post(BASE_URL, json=payload, timeout=timeout)
                if res.status_code != 200:
                    error_msg = f"[LLM_ERROR {res.status_code}] {res.text}"
                    logging.error(error_msg)
                    yield error_msg
                    return
                try:
                    obj = res.json()
                    choices = obj.get("choices")
                    if isinstance(choices, list) and choices:
                        first_choice = choices[0] if isinstance(choices[0], dict) else {}
                    else:
                        first_choice = {}
                    content = first_choice.get("message", {}).get("content")
                    if content:
                        yield content
                    return
                except Exception as exc:
                    error_msg = f"[LLM_EXCEPTION] Invalid JSON response: {str(exc)}"
                    logging.error(error_msg)
                    yield error_msg
                    return

            async with self.client.stream(
                "POST",
                BASE_URL,
                json=payload,
                timeout=timeout,
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

                        choices = obj.get("choices")
                        if isinstance(choices, list) and choices:
                            first_choice = choices[0] if isinstance(choices[0], dict) else {}
                        else:
                            first_choice = {}
                        delta = first_choice.get("delta", {})

                        content = delta.get("content")

                        if content:
                            yield content

                    except json.JSONDecodeError:
                        continue

                    except Exception as e:
                        logging.warning(f"Stream parse error: {e}")
                        continue

        except httpx.RequestError as e:
            error_msg = f"[NETWORK_ERROR] {str(e) or repr(e)}"
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
async def stream_llm(messages, model: str | None = None):
    async for token in llm_client.stream(messages, model=model):
        yield token


async def complete_llm(messages, model: str | None = None) -> str:
    """
    Collect streaming tokens into a single completion string.
    Keeps gateway logic simple and prevents hanging on upstream errors.
    """
    chunks: list[str] = []
    async for token in stream_llm(messages, model=model):
        if not token:
            continue
        # If upstream returns an error marker, fail fast.
        if token.startswith("[LLM_ERROR") or token.startswith("[NETWORK_ERROR]") or token.startswith("[LLM_EXCEPTION]"):
            raise RuntimeError(token)
        chunks.append(token)
    return "".join(chunks)


async def generate_image(
    prompt: str,
    model: str | None = None,
    size: str = "1024x1024",
    n: int = 1,
) -> dict:
    """
    Generate images via NVIDIA-compatible OpenAI image generations endpoint.
    Returns raw JSON payload from upstream.
    """
    if not isinstance(prompt, str) or not prompt.strip():
        raise RuntimeError("prompt must be a non-empty string")

    payload = {
        "model": model or IMAGE_GEN_MODEL,
        "prompt": prompt,
        "size": size,
        "n": max(1, int(n)),
    }

    try:
        res = await llm_client.client.post(IMAGE_BASE_URL, json=payload)
    except httpx.RequestError as exc:
        raise RuntimeError(f"[NETWORK_ERROR] {str(exc)}") from exc

    if res.status_code != 200:
        raise RuntimeError(f"[LLM_ERROR {res.status_code}] {res.text}")

    try:
        return res.json()
    except Exception as exc:
        raise RuntimeError(f"[LLM_EXCEPTION] Invalid JSON response: {str(exc)}") from exc


async def edit_image(
    *,
    prompt: str,
    image: str,
    model: str | None = None,
    size: str = "1024x1024",
    n: int = 1,
    mask: str | None = None,
) -> dict:
    """
    Edit images via NVIDIA-compatible OpenAI image edits endpoint.
    `image` and optional `mask` can be URL or base64 data URL (provider dependent).
    """
    if not isinstance(prompt, str) or not prompt.strip():
        raise RuntimeError("prompt must be a non-empty string")
    if not isinstance(image, str) or not image.strip():
        raise RuntimeError("image must be a non-empty string")

    payload = {
        "model": model or IMAGE_EDIT_MODEL,
        "prompt": prompt,
        "image": image,
        "size": size,
        "n": max(1, int(n)),
    }
    if isinstance(mask, str) and mask.strip():
        payload["mask"] = mask

    try:
        res = await llm_client.client.post(IMAGE_EDIT_BASE_URL, json=payload)
    except httpx.RequestError as exc:
        raise RuntimeError(f"[NETWORK_ERROR] {str(exc)}") from exc

    if res.status_code != 200:
        raise RuntimeError(f"[LLM_ERROR {res.status_code}] {res.text}")

    try:
        return res.json()
    except Exception as exc:
        raise RuntimeError(f"[LLM_EXCEPTION] Invalid JSON response: {str(exc)}") from exc