import time
import unittest
from unittest.mock import patch

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

    def test_heuristic_classifies_education_colon_fact(self):
        r = memory_service.classify_memory_candidate("education: Stamford Example College")
        self.assertTrue(r["should_store"])
        self.assertEqual((r.get("structured_data") or {}).get("education", "").lower(), "stamford example college")

    def test_assistant_turn_promotes_structured_fact_to_long_term(self):
        scope = "test-assistant-longterm-scope"
        with patch("memory.service.MEMORY_STORE_ASSISTANT_TURNS", True):
            memory_service.maybe_store_from_assistant_turn(
                text="Acknowledged — university: LTFixture Polytechnic for your academic records.",
                memory_scope=scope,
            )
        facts = memory_service.list_long_term_slot_facts(query="university", memory_scope=scope, limit=20)
        texts = [f.get("text", "").lower() for f in facts]
        self.assertTrue(any("ltfixture polytechnic" in t for t in texts))

    def test_assistant_turn_store_has_quality_guard(self):
        scope = "test-assistant-store-scope"
        with patch("memory.service.MEMORY_STORE_ASSISTANT_TURNS", True):
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

    def test_assistant_turn_skipped_when_store_assistant_disabled_by_default(self):
        scope = "test-assistant-store-default-off-scope"
        memory_service.maybe_store_from_assistant_turn(
            text="Confirmed hobby: skydiving",
            memory_scope=scope,
        )
        rows = memory_service.list_items(memory_scope=scope, limit=20)
        texts = [str(r.get("text") or "").lower() for r in rows]
        self.assertFalse(any("skydiving" in t for t in texts))

    def test_memory_filter_metrics_track_rejections(self):
        scope = "test-memory-filter-metrics-scope"
        before = memory_service.repo.get_short_runtime_metric_counts(
            memory_scope=scope,
            prefix="memory_filter.",
        )
        memory_service.maybe_store_from_user_turn(text="?", memory_scope=scope)
        after = memory_service.repo.get_short_runtime_metric_counts(
            memory_scope=scope,
            prefix="memory_filter.",
        )
        before_reject = int(before.get("memory_filter.user_text_filter_reject", 0))
        after_reject = int(after.get("memory_filter.user_text_filter_reject", 0))
        self.assertGreaterEqual(after_reject, before_reject + 1)

    def test_typed_classification_is_normalized_to_threshold(self):
        original_chain = memory_service._typed_classification_chain

        class _FakeTypedChain:
            def invoke(self, _text):
                return {
                    "should_store": True,
                    "importance_score": 0.2,
                    "category": "Work",
                    "structured_data": {"company": "Brotecs"},
                }

        try:
            memory_service._typed_classification_chain = _FakeTypedChain()
            classified = memory_service.classify_memory_candidate("my company is Brotecs")
        finally:
            memory_service._typed_classification_chain = original_chain

        self.assertFalse(classified["should_store"])
        self.assertEqual(classified["category"], "work")
        self.assertEqual((classified.get("structured_data") or {}).get("company"), "Brotecs")

    def test_list_recent_short_traces_preserves_created_at(self):
        """Reads must not bump created_at — retention TTL and ordering depend on it."""
        scope = "test-short-trace-created-at-scope"
        rid = "trace-created-at-fixture"
        memory_service.log_chat_trace(
            request_id=rid,
            memory_scope=scope,
            user_text="user ping",
            assistant_text="assistant pong",
            model="test-model",
            retrieved_items=[],
            had_error=False,
        )
        rows1 = memory_service.repo.list_recent_short_traces(memory_scope=scope, limit=20)
        row = next((r for r in rows1 if str(r.get("trace_id") or "") == rid), None)
        self.assertIsNotNone(row, "short_traces row should exist after log_chat_trace")
        ts_before = row["created_at"]
        time.sleep(0.06)
        rows2 = memory_service.repo.list_recent_short_traces(memory_scope=scope, limit=20)
        row2 = next((r for r in rows2 if str(r.get("trace_id") or "") == rid), None)
        self.assertIsNotNone(row2)
        self.assertEqual(ts_before, row2["created_at"])

    def test_assistant_turn_skipped_when_memory_auto_store_disabled(self):
        scope = "test-assistant-autostore-off-scope"
        with patch("memory.service.MEMORY_AUTO_STORE", False):
            memory_service.maybe_store_from_assistant_turn(
                text="Confirmed — hobby: synthetic autoflag quilting for your profile.",
                memory_scope=scope,
            )
        rows = memory_service.list_items(memory_scope=scope, limit=30)
        texts = [str(r.get("text") or "").lower() for r in rows]
        self.assertFalse(any("synthetic autoflag quilting" in t for t in texts))


if __name__ == "__main__":
    unittest.main()

