import unittest

from memory.service import memory_service


class MemoryServiceTest(unittest.TestCase):
    def setUp(self):
        self.scope = "test-suite-scope"
        memory_service.reindex(memory_scope=self.scope)

    def test_add_search_list_delete_cycle(self):
        add_res = memory_service.add_memory(
            text="My project codename is Aurora.",
            memory_scope=self.scope,
            source="manual",
            importance=0.9,
        )
        self.assertTrue(add_res["success"])
        memory_id = add_res["id"]

        results = memory_service.search(query="project codename", memory_scope=self.scope, limit=5)
        self.assertTrue(any(item["id"] == memory_id for item in results))

        listed = memory_service.list_items(memory_scope=self.scope, limit=20)
        self.assertTrue(any(item["id"] == memory_id for item in listed))

        del_res = memory_service.delete_item(item_id=memory_id, memory_scope=self.scope)
        self.assertTrue(del_res["success"])

    def test_reindex_returns_success(self):
        res = memory_service.reindex(memory_scope=self.scope)
        self.assertTrue(res["success"])
        self.assertEqual(res["memory_scope"], self.scope)


if __name__ == "__main__":
    unittest.main()

