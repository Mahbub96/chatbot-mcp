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

    def test_extract_generic_structured_facts_from_latex_text(self):
        latex_text = r"""
        \documentclass{article}
        \name{Mahbub Hasan}
        Email: mahbub@gmail.com
        Education: Stamford University Bangladesh
        \begin{document}
        \section{Skills}
        Python, FastAPI
        \end{document}
        """
        facts = memory_service._extract_structured_facts(latex_text)
        joined = " | ".join(facts).lower()
        self.assertIn("name: mahbub hasan", joined)
        self.assertIn("email: mahbub@gmail.com", joined)
        self.assertIn("education: stamford university bangladesh", joined)

    def test_store_structured_text_saves_full_and_facts(self):
        scope = "test-structured-store-scope"
        latex_text = r"""
        \documentclass{article}
        \name{Mahbub Hasan}
        Email: mahbub@gmail.com
        Education: Stamford University Bangladesh
        """
        memory_service._store_structured_facts(latex_text, memory_scope=scope)
        profile_items = memory_service.list_profile_memories(memory_scope=scope, limit=20)
        self.assertTrue(any((i.get("source") or "").lower() == "profile_full" for i in profile_items))
        self.assertTrue(any((i.get("source") or "").lower() == "profile_fact" for i in profile_items))

    def test_extractor_skips_latex_style_directives(self):
        text = r"""
        \definecolor{headcolor}{HTML}{1a1a1a}
        \usepackage{helvet}
        \href{https://mahbub.dev}{mahbub.dev}
        Email: mahbubcse96@gmail.com
        Name: Md Mahbub Alam
        """
        facts = memory_service._extract_structured_facts(text)
        joined = " | ".join(facts).lower()
        self.assertIn("email: mahbubcse96@gmail.com", joined)
        self.assertIn("name: md mahbub alam", joined)
        self.assertNotIn("definecolor:", joined)
        self.assertNotIn("usepackage:", joined)
        self.assertNotIn("href:", joined)

    def test_assistant_turn_store_has_quality_guard(self):
        scope = "test-assistant-store-scope"
        memory_service.maybe_store_from_assistant_turn(
            text="Here is a concise answer with concrete information.",
            memory_scope=scope,
        )
        memory_service.maybe_store_from_assistant_turn(
            text="I couldn't find this in your saved memory yet.",
            memory_scope=scope,
        )
        rows = memory_service.list_items(memory_scope=scope, limit=20)
        texts = [r["text"] for r in rows]
        self.assertTrue(any("concise answer" in t for t in texts))
        self.assertFalse(any("couldn't find this" in t.lower() for t in texts))


if __name__ == "__main__":
    unittest.main()

