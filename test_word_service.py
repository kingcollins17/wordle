import unittest
from unittest.mock import AsyncMock, MagicMock

from src.core.models.word import Word
from src.core.services.word_service import WordService


class TestWordService(unittest.IsolatedAsyncioTestCase):
    async def test_get_random_word_with_mock_session(self):
        # Mock session execution
        mock_session = AsyncMock()

        # Mock max_id result
        max_id_res = MagicMock()
        max_id_res.one_or_none.return_value = 10

        # Mock word result
        mock_word = Word(
            id="uuid-1",
            random_id=5,
            word="test",
            word_length=4,
            is_active=True,
        )
        word_res = MagicMock()
        word_res.first.return_value = mock_word

        # Set side effects for session.exec calls
        mock_session.exec.side_effect = [max_id_res, word_res]

        service = WordService(mock_session)
        result = await service.get_random(length=4)

        self.assertIsNotNone(result)
        self.assertEqual(result.word, "test")
        self.assertEqual(result.word_length, 4)
        self.assertEqual(mock_session.exec.call_count, 2)

    async def test_get_random_word_none_when_empty(self):
        mock_session = AsyncMock()

        max_id_res = MagicMock()
        max_id_res.one_or_none.return_value = None

        fallback_res = MagicMock()
        fallback_res.first.return_value = None

        mock_session.exec.side_effect = [max_id_res, fallback_res]

        service = WordService(mock_session)
        result = await service.get_random(length=4)

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
