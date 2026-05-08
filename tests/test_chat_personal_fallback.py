import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from gateway.main import app


class ChatPersonalFallbackTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.scope = "test-personal-fallback-scope"

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


if __name__ == "__main__":
    unittest.main()
