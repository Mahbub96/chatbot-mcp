import unittest

from gateway.memory_logic import build_memory_first_answer
from gateway.memory_logic import build_memory_fallback_answer
from gateway.memory_logic import detect_fact_slots
from gateway.memory_logic import is_personal_memory_query


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

    def test_information_about_query_is_personal_memory_query(self):
        self.assertTrue(is_personal_memory_query("I need information about mahbub alam"))

    def test_information_about_query_maps_to_name_slot(self):
        self.assertIn("name", detect_fact_slots("tell me about mahbub alam"))


if __name__ == "__main__":
    unittest.main()
