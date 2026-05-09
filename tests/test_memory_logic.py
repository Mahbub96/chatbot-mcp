import unittest

from gateway.memory_logic import build_memory_first_answer
from gateway.memory_logic import build_memory_fallback_answer
from gateway.memory_logic import blocks_semantic_memory_context_fallback
from gateway.memory_logic import detect_fact_slots
from gateway.memory_logic import is_personal_memory_query
from gateway.memory_logic import memories_for_semantic_context_fallback
from gateway.memory_logic import select_context_memories
from gateway.memory_logic import select_context_memories_relaxed_personal_fallback


class MemoryLogicTest(unittest.TestCase):
    def test_non_personal_query_does_not_use_memory_first(self):
        answer = build_memory_first_answer(
            "Tell me a random fun fact about the Roman Empire",
            [{"text": "tell me everything you know about me", "source": "chat_user", "score": 0.9}],
        )
        self.assertIsNone(answer)

    def test_personal_query_can_use_memory_first(self):
        answer = build_memory_first_answer(
            "what is my university name",
            [{"text": "university: BUET", "source": "profile_fact", "score": 0.9}],
        )
        self.assertEqual(answer, "Saved fact: university: BUET")

    def test_university_query_does_not_match_name_fact(self):
        answer = build_memory_first_answer(
            "what is my university name",
            [{"text": "name: Md Mahbub Alam", "source": "profile_fact", "score": 0.9}],
        )
        self.assertIsNone(answer)

    def test_school_name_query_does_not_match_person_name_fact(self):
        answer = build_memory_first_answer(
            "what is my school name",
            [{"text": "name: Md Mahbub Alam", "source": "profile_fact", "score": 0.9}],
        )
        self.assertIsNone(answer)

    def test_school_name_query_maps_to_university_slot(self):
        slots = detect_fact_slots("school name ?")
        self.assertIn("university", slots)
        self.assertNotIn("name", slots)

    def test_typo_school_spelling_maps_to_university_slot_not_name(self):
        slots = detect_fact_slots("my scholl name ?")
        self.assertIn("university", slots)
        self.assertNotIn("name", slots)

    def test_typo_school_name_query_does_not_match_person_name_fact(self):
        answer = build_memory_first_answer(
            "my scholl name ?",
            [{"text": "name: Md Mahbub Alam", "source": "profile_fact", "score": 0.9}],
        )
        self.assertIsNone(answer)

    def test_typo_school_name_query_matches_education_fact(self):
        answer = build_memory_first_answer(
            "my scholl name ?",
            [{"text": "education: Stamford University Bangladesh", "source": "profile_fact", "score": 0.9}],
        )
        self.assertEqual(answer, "Saved fact: education: Stamford University Bangladesh")

    def test_university_fallback_skips_profile_full_blob(self):
        answer = build_memory_fallback_answer(
            "what is my university name",
            [
                {"text": "\\documentclass{article} ... Stamford University Bangladesh ...", "source": "profile_full"},
                {"text": "education: Stamford University Bangladesh", "source": "profile_fact"},
            ],
        )
        self.assertEqual(answer, "Saved fact: education: Stamford University Bangladesh")

    def test_detect_work_slot(self):
        self.assertIn("work", detect_fact_slots("where I work ?"))
        self.assertIn("work", detect_fact_slots("my office name"))
        self.assertIn("work", detect_fact_slots("what is my role?"))

    def test_profile_full_work_query_extracts_generic_snippet(self):
        answer = build_memory_fallback_answer(
            "where I work ?",
            [
                {
                    "source": "profile_full",
                    "text": "Email: x@example.com. Experience: Worked at Brotecs for more than 2 years as Software Engineer role in backend team.",
                }
            ],
        )
        self.assertIsNotNone(answer)
        self.assertIn("Saved fact:", answer)
        self.assertIn("Brotecs", answer)
        self.assertNotIn("Email:", answer)

    def test_work_query_is_personal_memory_query(self):
        self.assertTrue(is_personal_memory_query("where I work ?"))

    def test_city_live_question_is_personal_memory_query(self):
        self.assertTrue(is_personal_memory_query("what city do i live in"))
        self.assertTrue(is_personal_memory_query("where do i live"))

    def test_relaxed_personal_fallback_pool_keeps_low_importance_assistant_facts(self):
        rows = [
            {"text": "company: Brotecs", "source": "chat_assistant", "score": 0.82, "importance": 0.35},
        ]
        self.assertEqual(select_context_memories("what is my company", rows), [])
        relaxed = select_context_memories_relaxed_personal_fallback("what is my company", rows)
        self.assertEqual(len(relaxed), 1)

    def test_relaxed_personal_fallback_drops_unstructured_long_chat_text(self):
        long_blob = "word " * 120
        rows = [{"text": long_blob, "source": "chat_user", "score": 0.9, "importance": 0.9}]
        self.assertEqual(select_context_memories_relaxed_personal_fallback("what is my hobby", rows), [])

    def test_relaxed_personal_fallback_keeps_compact_structured_line_over_500_chars(self):
        text = "education: " + ("detail-" * 90)
        self.assertGreater(len(text), 500)
        rows = [{"text": text, "source": "profile_fact", "score": 0.9, "importance": 0.9}]
        self.assertEqual(select_context_memories("what is my university name", rows), [])
        relaxed = select_context_memories_relaxed_personal_fallback("what is my university name", rows)
        self.assertEqual(len(relaxed), 1)

    def test_information_about_query_is_personal_memory_query(self):
        self.assertTrue(is_personal_memory_query("I need information about mahbub alam"))

    def test_information_about_query_maps_to_name_slot(self):
        self.assertIn("name", detect_fact_slots("tell me about mahbub alam"))

    def test_semantic_fallback_block_narrow_for_general_questions(self):
        self.assertFalse(blocks_semantic_memory_context_fallback("Tell me about distributed consensus briefly"))
        self.assertFalse(blocks_semantic_memory_context_fallback("Explain how Raft handles leader elections"))

    def test_semantic_fallback_block_true_for_possessive_profile(self):
        self.assertTrue(blocks_semantic_memory_context_fallback("what is my university name"))
        self.assertTrue(blocks_semantic_memory_context_fallback("where do i work ?"))

    def test_personal_about_me_query_is_treated_as_personal(self):
        self.assertTrue(is_personal_memory_query("tell me about me"))

    def test_semantic_fallback_prefers_best_ranked_item(self):
        q = "notes on raft consensus"
        hits = [
            {"text": "Weak marginal snippet about lunch menus.", "source": "chat_user", "score": 0.22},
            {"text": "Raft handles leader election and log replication.", "source": "manual", "score": 0.78},
        ]
        got = memories_for_semantic_context_fallback(
            q,
            hits,
            limit=1,
            min_score=0.2,
            min_overlap=0.12,
            max_chars=500,
        )
        self.assertEqual(len(got), 1)
        self.assertIn("Raft", got[0]["text"])

    def test_semantic_fallback_injects_high_score_hit(self):
        q = "explain distributed consensus briefly"
        hits = [
            {
                "text": "Distributed consensus protocols let nodes agree despite failures; Raft is common.",
                "source": "chat_user",
                "score": 0.72,
            }
        ]
        got = memories_for_semantic_context_fallback(
            q,
            hits,
            limit=3,
            min_score=0.2,
            min_overlap=0.12,
            max_chars=500,
        )
        self.assertEqual(len(got), 1)
        self.assertIn("Raft", got[0]["text"])

    def test_semantic_fallback_skips_low_signal_item(self):
        q = "explain quantum field theory"
        hits = [
            {
                "text": "Unrelated baking tips for sourdough starters overnight.",
                "source": "chat_user",
                "score": 0.08,
            }
        ]
        got = memories_for_semantic_context_fallback(
            q,
            hits,
            limit=3,
            min_score=0.25,
            min_overlap=0.25,
            max_chars=500,
        )
        self.assertEqual(got, [])

    def test_semantic_fallback_truncates_long_text(self):
        q = "notes on caching"
        body = "Caching memo " + ("x" * 700)
        hits = [{"text": body, "source": "manual", "score": 0.9}]
        got = memories_for_semantic_context_fallback(
            q,
            hits,
            limit=2,
            min_score=0.2,
            min_overlap=0.12,
            max_chars=120,
        )
        self.assertEqual(len(got), 1)
        self.assertLessEqual(len(got[0]["text"]), 123)
        self.assertTrue(got[0]["text"].endswith("..."))


if __name__ == "__main__":
    unittest.main()
