import random
import logging
from typing import Optional, List
from sqlmodel import select, col
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy import func
from fastapi import Depends

from src.core.models.word import Word
from src.database.db_connection_manager import get_async_session, get_mysql_manager

logger = logging.getLogger(__name__)


class WordService:
    """
    Service for managing word operations including efficient random selection.
    """

    def __init__(self, session: Optional[AsyncSession] = None):
        self.session = session

    async def get_random(
        self,
        length: Optional[int] = 4,
        count: int = 1,
        session: Optional[AsyncSession] = None,
    ) -> List[Word]:
        """
        Fetch random words from the database of the specified length.
        
        Args:
            length: Target word length (default: 4, pass None for any length)
            count: Number of random words to return (default: 1)
            session: Optional AsyncSession override
            
        Returns:
            List[Word]: A list of randomly selected Word model instances.
        """
        sess = session or self.session

        if sess is not None:
            return await self._get_random_with_session(sess, length=length, count=count)
        else:
            manager = get_mysql_manager()
            async with manager.session() as db_session:
                return await self._get_random_with_session(db_session, length=length, count=count)

    async def _get_random_with_session(
        self,
        session: AsyncSession,
        length: Optional[int] = 4,
        count: int = 1,
    ) -> List[Word]:
        if count <= 0:
            return []

        stmt = select(Word).where(Word.is_active == True)
        if length is not None:
            stmt = stmt.where(Word.word_length == length)

        stmt = stmt.order_by(func.random()).limit(count)
        exec_res = await session.exec(stmt)
        return list(exec_res.all())


def get_word_service(
    session: AsyncSession = Depends(get_async_session),
) -> WordService:
    """FastAPI dependency provider for WordService."""
    return WordService(session)


async def seed_initial_words() -> int:
    """
    Startup function to seed initial words from fours_json, fives_json, sixes_json into database.
    Converts all word strings to UPPERCASE before insertion.
    Uses bulk insertion for maximum performance and avoids duplicating existing entries.
    
    Returns:
        int: Number of new words inserted.
    """
    from src.game.fours_json import fours_json
    from src.game.fives_json import fives_json
    from src.game.sixes_json import sixes_json
    from src.core.repository import Repository

    all_words: dict[str, str] = {}
    for source_dict in (fours_json, fives_json, sixes_json):
        for raw_word, raw_meaning in source_dict.items():
            upper_word = raw_word.strip().upper()
            if upper_word:
                meaning = raw_meaning.strip() if raw_meaning else ""
                all_words[upper_word] = meaning

    if not all_words:
        logger.info("No words found in source JSON files to seed.")
        return 0

    manager = get_mysql_manager()
    async with manager.session() as session:
        # Fetch existing words from database
        res = await session.exec(select(Word.word))
        existing_words = {w.upper() for w in res.all()}

        # Filter out words that already exist
        words_to_insert = {w: m for w, m in all_words.items() if w not in existing_words}
        if not words_to_insert:
            logger.info("All initial words are already seeded in the database.")
            return 0

        # Fetch current max random_id
        max_id_res = await session.exec(select(func.max(Word.random_id)))
        current_max_id = max_id_res.one_or_none() or 0

        # Create Word entities
        entities = []
        for idx, (word_str, meaning_str) in enumerate(words_to_insert.items(), start=1):
            entities.append(
                Word(
                    word=word_str,
                    meaning=meaning_str,
                    word_length=len(word_str),
                    is_active=True,
                    random_id=current_max_id + idx,
                )
            )

        # Fast bulk insert using optimized add_many
        repo = Repository(Word, session)
        await repo.add_many(entities, refresh=False)
        logger.info(f"Successfully seeded {len(entities)} initial words into the database.")
        return len(entities)
