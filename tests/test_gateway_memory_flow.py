import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from gateway.main import app


class GatewayMemoryFlowTest(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.scope = "test-gateway-memory-scope"

    def test_memory_item_endpoints(self):
        add_res = self.client.post(
            "/memory/items",
            json={
                "memory_scope": self.scope,
                "text": "My favorite framework is FastAPI.",
                "source": "manual",
                "importance": 0.8,
            },
        )
        self.assertEqual(add_res.status_code, 200)
        add_body = add_res.json()
        self.assertTrue(add_body.get("success"))
        item_id = add_body.get("id")

        search_res = self.client.post(
            "/memory/search",
            json={"memory_scope": self.scope, "query": "favorite framework", "limit": 5},
        )
        self.assertEqual(search_res.status_code, 200)
        self.assertTrue(search_res.json().get("success"))

        list_res = self.client.get(f"/memory/items?memory_scope={self.scope}&limit=20")
        self.assertEqual(list_res.status_code, 200)
        self.assertTrue(list_res.json().get("success"))

        reindex_res = self.client.post("/memory/reindex", json={"memory_scope": self.scope})
        self.assertEqual(reindex_res.status_code, 200)
        self.assertTrue(reindex_res.json().get("success"))

        del_res = self.client.delete(f"/memory/items/{item_id}?memory_scope={self.scope}")
        self.assertEqual(del_res.status_code, 200)
        self.assertTrue(del_res.json().get("success"))

    def test_image_chat_generic_refusal_is_rewritten(self):
        fake_complete = AsyncMock(return_value="I'm not able to provide help with this conversation.")

        with patch("gateway.controllers.chat_controller.complete_llm", fake_complete):
            res = self.client.post(
                "/v1/chat/completions",
                json={
                    "stream": False,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "explain this image"},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": "https://example.com/demo.png"},
                                },
                            ],
                        }
                    ],
                },
            )
        self.assertEqual(res.status_code, 200)
        content = res.json()["choices"][0]["message"]["content"]
        self.assertIn("couldn't analyze the image", content.lower())

    def test_image_chat_subject_matter_refusal_is_rewritten(self):
        fake_complete = AsyncMock(return_value="I'm not going to engage in this subject matter.")

        with patch("gateway.controllers.chat_controller.complete_llm", fake_complete):
            res = self.client.post(
                "/v1/chat/completions",
                json={
                    "stream": False,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "describe this image"},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": "https://example.com/demo.png"},
                                },
                            ],
                        }
                    ],
                },
            )
        self.assertEqual(res.status_code, 200)
        content = res.json()["choices"][0]["message"]["content"]
        self.assertIn("couldn't analyze the image", content.lower())

    def test_image_chat_retries_on_initial_refusal(self):
        fake_complete = AsyncMock(
            side_effect=[
                "I'm not going to engage in this subject matter.",
                "A dark-themed dashboard UI is shown with glowing circular audio visualizer.",
            ]
        )

        with patch("gateway.controllers.chat_controller.complete_llm", fake_complete):
            res = self.client.post(
                "/v1/chat/completions",
                json={
                    "stream": False,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {"type": "text", "text": "describe this image"},
                                {
                                    "type": "image_url",
                                    "image_url": {"url": "https://example.com/demo.png"},
                                },
                            ],
                        }
                    ],
                },
            )
        self.assertEqual(res.status_code, 200)
        content = res.json()["choices"][0]["message"]["content"]
        self.assertIn("dashboard ui", content.lower())
        self.assertEqual(fake_complete.await_count, 2)

    def test_image_chat_autoinjects_instruction_when_text_missing(self):
        fake_complete = AsyncMock(return_value="An image with two people and a laptop on a desk.")

        with patch("gateway.controllers.chat_controller.complete_llm", fake_complete):
            res = self.client.post(
                "/v1/chat/completions",
                json={
                    "stream": False,
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {"url": "https://example.com/demo.png"},
                                },
                            ],
                        }
                    ],
                },
            )
        self.assertEqual(res.status_code, 200)
        self.assertGreaterEqual(fake_complete.await_count, 1)
        first_messages = fake_complete.await_args_list[0].args[0]
        first_user = next(msg for msg in first_messages if msg.get("role") == "user")
        first_part = first_user["content"][0]
        self.assertEqual(first_part["type"], "text")
        self.assertIn("describe this visual content professionally", first_part["text"].lower())


if __name__ == "__main__":
    unittest.main()

