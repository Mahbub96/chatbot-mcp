import unittest
from unittest.mock import MagicMock, patch

import memory.services.retrieval_service as retrieval_module
from memory.services.retrieval_service import RetrievalService


class RetrievalServiceTest(unittest.TestCase):
    def _patch_empty_stages(self):
        return patch.multiple(
            "memory.services.retrieval_service.memory_service",
            list_short_term_slot_facts=MagicMock(return_value=[]),
            list_short_term_context_facts=MagicMock(return_value=[]),
            list_short_term_slot_facts_any_scope=MagicMock(return_value=[]),
            list_short_term_context_facts_any_scope=MagicMock(return_value=[]),
            list_long_term_slot_facts=MagicMock(return_value=[]),
            list_long_term_slot_facts_any_scope=MagicMock(return_value=[]),
            search=MagicMock(return_value=[]),
            list_items=MagicMock(return_value=[]),
            list_profile_memories_any_scope=MagicMock(return_value=[]),
            list_profile_facts_any_scope=MagicMock(return_value=[]),
        )

    def test_any_scope_fallback_disabled_by_default(self):
        service = RetrievalService()
        with self._patch_empty_stages(), patch(
            "memory.services.retrieval_service.MEMORY_ANY_SCOPE_FALLBACK_ENABLED",
            False,
        ), patch.object(
            retrieval_module.memory_service.repo,
            "list_all",
            MagicMock(return_value=[]),
        ) as mock_list_all:
            service.retrieve(query="what is my university", memory_scope="scope-x", limit=3)
        mock_list_all.assert_not_called()

    def test_any_scope_fallback_requires_personal_intent(self):
        service = RetrievalService()
        with self._patch_empty_stages(), patch(
            "memory.services.retrieval_service.MEMORY_ANY_SCOPE_FALLBACK_ENABLED",
            True,
        ), patch.object(
            retrieval_module.memory_service.repo,
            "list_all",
            MagicMock(return_value=[]),
        ) as mock_list_all:
            service.retrieve(query="explain distributed consensus", memory_scope="scope-x", limit=3)
        mock_list_all.assert_not_called()


if __name__ == "__main__":
    unittest.main()
