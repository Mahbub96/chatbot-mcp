import unittest

from router.intent_router import normalize_intent_suggestion, route_intent


class IntentRouterTest(unittest.TestCase):
    def test_tool_intent_is_detected(self):
        route = route_intent("please read file test.txt", has_memory_hits=False, has_multimodal_input=False)
        self.assertEqual(route.route, "tool")
        self.assertTrue(route.allow_tool)

    def test_memory_hit_prefers_memory_db_route(self):
        route = route_intent("what is my university", has_memory_hits=True, has_multimodal_input=False)
        self.assertEqual(route.route, "memory_db")
        self.assertFalse(route.allow_tool)

    def test_normalize_intent_suggestion_accepts_known_intents(self):
        self.assertEqual(normalize_intent_suggestion("internet-search"), "internet_search")
        self.assertEqual(normalize_intent_suggestion(" TOOL "), "tool")
        self.assertIsNone(normalize_intent_suggestion("unknown"))


if __name__ == "__main__":
    unittest.main()
