import random
import logging
from typing import Optional
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
        length: int = 4,
        session: Optional[AsyncSession] = None,
    ) -> Optional[Word]:
        """
        Fetch a random word from the database of the specified length using an indexed random_id.
        
        Args:
            length: Target word length (default: 4)
            session: Optional AsyncSession override
            
        Returns:
            Optional[Word]: A randomly selected Word model instance or None if no matching word is found.
        """
        sess = session or self.session

        if sess is not None:
            return await self._get_random_with_session(sess, length)
        else:
            manager = get_mysql_manager()
            async with manager.session() as db_session:
                return await self._get_random_with_session(db_session, length)

    async def _get_random_with_session(
        self,
        session: AsyncSession,
        length: int = 4,
    ) -> Optional[Word]:
        # 1. Get max random_id for active words of specified length
        max_id_stmt = select(func.max(Word.random_id)).where(Word.is_active == True)
        if length is not None:
            max_id_stmt = max_id_stmt.where(Word.word_length == length)

        res = await session.exec(max_id_stmt)
        max_id = res.one_or_none()

        if max_id is not None and max_id > 0:
            # 2. Select a random target ID between 1 and max_id
            target_id = random.randint(1, max_id)

            # 3. Query for first word with random_id >= target_id
            stmt = (
                select(Word)
                .where(
                    col(Word.random_id) >= target_id,
                    Word.is_active == True,
                )
            )
            if length is not None:
                stmt = stmt.where(Word.word_length == length)

            stmt = stmt.order_by(col(Word.random_id)).limit(1)

            exec_res = await session.exec(stmt)
            word = exec_res.first()

            if word:
                return word

            # Wrap-around query if target_id was beyond highest random_id for this length
            wrap_stmt = (
                select(Word)
                .where(
                    col(Word.random_id) >= 1,
                    Word.is_active == True,
                )
            )
            if length is not None:
                wrap_stmt = wrap_stmt.where(Word.word_length == length)

            wrap_stmt = wrap_stmt.order_by(col(Word.random_id)).limit(1)
            exec_res = await session.exec(wrap_stmt)
            word = exec_res.first()

            if word:
                return word

        # Fallback query for cases where random_id is missing or not set
        fallback_stmt = select(Word).where(Word.is_active == True)
        if length is not None:
            fallback_stmt = fallback_stmt.where(Word.word_length == length)

        fallback_stmt = fallback_stmt.order_by(func.random()).limit(1)
        exec_res = await session.exec(fallback_stmt)
        return exec_res.first()


def get_word_service(
    session: AsyncSession = Depends(get_async_session),
) -> WordService:
    """FastAPI dependency provider for WordService."""
    return WordService(session)
