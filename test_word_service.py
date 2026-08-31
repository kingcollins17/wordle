import unittest
from unittest.mock import AsyncMock, MagicMock

from src.core.models.word import Word
from src.core.services.word_service import WordService


class TestWordService(unittest.IsolatedAsyncioTestCase):
    async def test_get_random_word_with_mock_session(self):
        mock_session = AsyncMock()

        mock_word = Word(
            id="uuid-1",
            random_id=5,
            word="TEST",
            word_length=4,
            is_active=True,
        )
        word_res = MagicMock()
        word_res.all.return_value = [mock_word]

        mock_session.exec.return_value = word_res

        service = WordService(mock_session)
        result = await service.get_random(length=4, count=1)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].word, "TEST")
        self.assertEqual(result[0].word_length, 4)

    async def test_get_random_words_multiple(self):
        mock_session = AsyncMock()

        mock_words = [
            Word(id="uuid-1", word="TEST", word_length=4, is_active=True),
            Word(id="uuid-2", word="WORD", word_length=4, is_active=True),
        ]
        word_res = MagicMock()
        word_res.all.return_value = mock_words

        mock_session.exec.return_value = word_res

        service = WordService(mock_session)
        result = await service.get_random(length=4, count=2)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].word, "TEST")
        self.assertEqual(result[1].word, "WORD")

    async def test_get_random_word_empty(self):
        mock_session = AsyncMock()

        word_res = MagicMock()
        word_res.all.return_value = []

        mock_session.exec.return_value = word_res

        service = WordService(mock_session)
        result = await service.get_random(length=4, count=5)

        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
