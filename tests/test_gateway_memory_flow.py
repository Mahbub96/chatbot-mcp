import unittest

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


if __name__ == "__main__":
    unittest.main()

