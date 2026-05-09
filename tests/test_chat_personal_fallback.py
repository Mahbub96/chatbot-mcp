import unittest
import asyncio
from unittest.mock import patch

from fastapi.testclient import TestClient

from gateway.main import app
from gateway.controllers.chat_controller import fallback_context_memories_when_unmatched
from gateway.controllers.chat_controller import _stream_text_llm_chat_completion


class ChatPersonalFallbackTest(unittest.TestCase):
    def setUp(self):
        self._client_ctx = TestClient(app)
        self.client = self._client_ctx.__enter__()
        self.scope = "test-personal-fallback-scope"

    def tearDown(self):
        self._client_ctx.__exit__(None, None, None)


    def test_unmatched_fallback_prefers_profile_fact(self):
        rows = [
            {"text": "role: backend engineer", "source": "short_trace", "score": 0.95, "importance": 0.9},
            {"text": "name: Test User", "source": "profile_fact", "score": 0.2, "importance": 0.8},
        ]
        picked = fallback_context_memories_when_unmatched(
            user_text="what is my name",
            retrieved_items=rows,
            limit=1,
        )
        self.assertEqual(len(picked), 1)
        self.assertEqual((picked[0].get("source") or "").lower(), "profile_fact")

    def test_unmatched_fallback_ignores_assistant_response_context(self):
        rows = [
            {
                "text": "I don't have exact saved info right now.",
                "source": "short_trace_context",
                "score": 0.9,
                "importance": 0.9,
                "structured_data": {"source_field": "assistant_response"},
            },
            {"text": "company: Brotecs", "source": "profile_fact", "score": 0.5, "importance": 0.8},
        ]
        picked = fallback_context_memories_when_unmatched(
            user_text="where i work",
            retrieved_items=rows,
            limit=2,
        )
        joined = " | ".join((x.get("text") or "") for x in picked).lower()
        self.assertNotIn("i don't have", joined)
        self.assertIn("company: brotecs", joined)

    def test_unmatched_fallback_includes_chat_user_when_curated_sources_absent(self):
        rows = [
            {"text": "city: Dhaka", "source": "chat_user", "score": 0.72, "importance": 0.55},
        ]
        picked = fallback_context_memories_when_unmatched(
            user_text="what city do i live in",
            retrieved_items=rows,
            limit=3,
        )
        self.assertEqual(len(picked), 1)
        self.assertEqual((picked[0].get("source") or "").lower(), "chat_user")

    def test_unmatched_fallback_prefers_profile_fact_over_chat_user(self):
        rows = [
            {"text": "city: Chittagong", "source": "chat_user", "score": 0.95, "importance": 0.9},
            {"text": "city: Dhaka", "source": "profile_fact", "score": 0.4, "importance": 0.6},
        ]
        picked = fallback_context_memories_when_unmatched(
            user_text="what city do i live in",
            retrieved_items=rows,
            limit=1,
        )
        self.assertEqual(len(picked), 1)
        self.assertEqual((picked[0].get("source") or "").lower(), "profile_fact")

    def test_unmatched_fallback_uses_relaxed_pool_when_strict_filters_everything(self):
        rows = [
            {"text": "company: Brotecs", "source": "chat_assistant", "score": 0.85, "importance": 0.35},
        ]
        picked = fallback_context_memories_when_unmatched(
            user_text="what is my company",
            retrieved_items=rows,
            limit=2,
        )
        self.assertEqual(len(picked), 1)
        self.assertIn("brotecs", (picked[0].get("text") or "").lower())

    def test_non_stream_uses_local_memory_when_llm_says_unknown(self):
        async def fake_complete(_messages, model=None):
            return "I don't have information about your university name."

        with patch("gateway.controllers.chat_controller.complete_llm", fake_complete):
            add = self.client.post(
                "/memory/items",
                json={
                    "memory_scope": self.scope,
                    "text": "university: Stamford University Bangladesh",
                    "source": "profile_fact",
                    "importance": 0.9,
                },
            )
            self.assertEqual(add.status_code, 200)
            res = self.client.post(
                "/v1/chat/completions",
                json={
                    "stream": False,
                    "memory_scope": self.scope,
                    "messages": [{"role": "user", "content": "what is my university name"}],
                },
            )
        self.assertEqual(res.status_code, 200)
        content = res.json()["choices"][0]["message"]["content"]
        self.assertIn("Saved fact: university:", content)

    def test_stream_image_sends_progress_chunk(self):
        async def fake_complete(_messages, model=None):
            return "Image looks good."

        with patch("gateway.controllers.chat_controller.complete_llm", fake_complete):
            res = self.client.post(
                "/v1/chat/completions",
                json={
                    "stream": True,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "explain this image"},
                                {"type": "image_url", "image_url": {"url": "https://example.com/demo.png"}},
                            ],
                        }
                    ],
                },
            )
        self.assertEqual(res.status_code, 200)
        body = res.text
        self.assertIn("Processing image...", body)
        self.assertIn("Image looks good.", body)

    def test_allows_inline_base64_image_url(self):
        async def fake_complete(_messages, model=None):
            return "Inline image accepted."

        with patch("gateway.controllers.chat_controller.complete_llm", fake_complete):
            res = self.client.post(
                "/v1/chat/completions",
                json={
                    "stream": False,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "describe"},
                                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
                            ],
                        }
                    ],
                },
            )
        self.assertEqual(res.status_code, 200)
        self.assertIn("Inline image accepted.", res.text)

    def test_allows_private_localhost_image_url(self):
        async def fake_complete(_messages, model=None):
            return "Local URL accepted."

        with patch("gateway.controllers.chat_controller.complete_llm", fake_complete):
            res = self.client.post(
                "/v1/chat/completions",
                json={
                    "stream": False,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "describe"},
                                {"type": "image_url", "image_url": {"url": "http://127.0.0.1:9000/demo.png"}},
                            ],
                        }
                    ],
                },
            )
        self.assertEqual(res.status_code, 200)
        self.assertIn("Local URL accepted.", res.text)

    def test_allows_file_scheme_image_url(self):
        async def fake_complete(_messages, model=None):
            return "File URL accepted."

        with patch("gateway.controllers.chat_controller.complete_llm", fake_complete):
            res = self.client.post(
                "/v1/chat/completions",
                json={
                    "stream": False,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "describe"},
                                {"type": "image_url", "image_url": {"url": "file:///tmp/demo.png"}},
                            ],
                        }
                    ],
                },
            )
        self.assertEqual(res.status_code, 200)
        self.assertIn("File URL accepted.", res.text)

    def test_stream_stall_after_first_token_terminates(self):
        async def hanging_stream(_messages, model=None):
            yield "hello"
            while True:
                await asyncio.sleep(1)

        async def _collect():
            out = []
            async for chunk in _stream_text_llm_chat_completion(
                llm_messages=[{"role": "user", "content": "what is my name"}],
                upstream_model="fake-model",
                user_text="what is my name",
                memory_scope=self.scope,
                query_matched_memories=[],
                retrieval_trace_items=[],
                request_id="r-1",
                hold_personal_stream=False,
                log_step=lambda _name: None,
            ):
                out.append(chunk)
            return "".join(out)

        with (
            patch("gateway.controllers.chat_controller.stream_llm", hanging_stream),
            patch("gateway.controllers.chat_controller.TEXT_STREAM_STATUS_INTERVAL_SECONDS", 0.01),
            patch("gateway.controllers.chat_controller.MAX_STREAM_IDLE_TIMEOUTS", 1),
        ):
            body = asyncio.run(_collect())
        self.assertIn("Stream stalled while generating response", body)
        self.assertIn("[DONE]", body)

    def test_stream_post_first_token_duration_cap_returns_partial_and_done(self):
        async def long_tail_stream(_messages, model=None):
            yield "partial answer"
            while True:
                await asyncio.sleep(1)

        async def _collect():
            out = []
            async for chunk in _stream_text_llm_chat_completion(
                llm_messages=[{"role": "user", "content": "what is my university name"}],
                upstream_model="fake-model",
                user_text="what is my university name",
                memory_scope=self.scope,
                query_matched_memories=[],
                retrieval_trace_items=[],
                request_id="r-2",
                hold_personal_stream=False,
                log_step=lambda _name: None,
            ):
                out.append(chunk)
            return "".join(out)

        with (
            patch("gateway.controllers.chat_controller.stream_llm", long_tail_stream),
            patch("gateway.controllers.chat_controller.TEXT_STREAM_STATUS_INTERVAL_SECONDS", 0.01),
            patch("gateway.controllers.chat_controller.MAX_STREAM_IDLE_TIMEOUTS", 500),
            patch("gateway.controllers.chat_controller.MAX_STREAM_POST_FIRST_TOKEN_SECONDS", 0.02),
        ):
            body = asyncio.run(_collect())
        self.assertIn("partial answer", body)
        self.assertIn("duration capped for latency control", body)
        self.assertIn("[DONE]", body)


if __name__ == "__main__":
    unittest.main()
