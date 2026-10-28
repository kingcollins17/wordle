import logging
from typing import Optional, List
from sqlmodel import select, col
from sqlmodel.ext.asyncio.session import AsyncSession
from fastapi import Depends

from src.core.models.reward import Reward
from src.core.models.user import User
from src.core.utils.time import get_current_time
from src.database.db_connection_manager import get_async_session, get_mysql_manager

logger = logging.getLogger(__name__)


class RewardService:
    """
    Service for managing rewards, including awarding items to users and tracking read status.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def reward(
        self,
        user_id: str,
        coins: int = 0,
        fish_out: int = 0,
        reveal_letter: int = 0,
        word_meaning: int = 0,
        *,
        fish_outs: Optional[int] = None,
        reveal_letters: Optional[int] = None,
        word_meanings: Optional[int] = None,
        title: Optional[str] = None,
        description: Optional[str] = None,
        apply_to_user: bool = False,
    ) -> Reward:
        """
        Insert a reward entry for a specific user.

        Args:
            user_id: Target user ID
            coins: Amount of coins
            fish_out: Amount of fish out power-ups (or use fish_outs)
            reveal_letter: Amount of reveal letter power-ups (or use reveal_letters)
            word_meaning: Amount of word meaning power-ups (or use word_meanings)
            fish_outs: Optional alias for fish_out
            reveal_letters: Optional alias for reveal_letter
            word_meanings: Optional alias for word_meaning
            title: Optional short reward title
            description: Optional detailed message/reason
            apply_to_user: If True, also directly increment user's balance
            session: Optional AsyncSession override

        Returns:
            Reward: The created reward record.
        """
        final_fish_out = fish_outs if fish_outs is not None else fish_out
        final_reveal_letter = reveal_letters if reveal_letters is not None else reveal_letter
        final_word_meaning = word_meanings if word_meanings is not None else word_meaning

        sess = self.session
        return await self._reward_with_session(
                sess,
                user_id=user_id,
                coins=coins,
                fish_out=final_fish_out,
                reveal_letter=final_reveal_letter,
                word_meaning=final_word_meaning,
                title=title,
                description=description,
            )
        
    async def _reward_with_session(
        self,
        session: AsyncSession,
        user_id: str,
        coins: int,
        fish_out: int,
        reveal_letter: int,
        word_meaning: int,
        title: Optional[str],
        description: Optional[str],
    ) -> Reward:
        reward_entry = Reward(
            user_id=user_id,
            coins=coins,
            fish_out=fish_out,
            reveal_letter=reveal_letter,
            word_meaning=word_meaning,
            is_read=False,
            title=title,
            description=description,
        )

        session.add(reward_entry)

        user = await session.get(User, user_id)
        if user:
            user.coins += coins
            user.fish_out += fish_out
            user.reveal_letter += reveal_letter
            user.word_meaning += word_meaning
            user.updated_at = get_current_time()
            session.add(user)

        await session.commit()
        await session.refresh(reward_entry)
        logger.info(
            f"Reward {reward_entry.id} granted to user {user_id}: "
            f"coins={coins}, fish_out={fish_out}, reveal_letter={reveal_letter}, word_meaning={word_meaning}"
        )
        return reward_entry

    async def mark_as_read(
        self,
        reward_id: str,
        user_id: Optional[str] = None,
    ) -> Optional[Reward]:
        """
        Mark a reward entry as read.

        Args:
            reward_id: Primary key ID of the reward
            user_id: Optional user ID to verify reward ownership
            session: Optional AsyncSession override

        Returns:
            Optional[Reward]: The updated reward if found, None otherwise.
        """
        sess = self.session
   
        return await self._mark_as_read_with_session(sess, reward_id=reward_id, user_id=user_id)
        
    async def _mark_as_read_with_session(
        self,
        session: AsyncSession,
        reward_id: str,
        user_id: Optional[str] = None,
    ) -> Optional[Reward]:
        stmt = select(Reward).where(Reward.id == reward_id)
        if user_id is not None:
            stmt = stmt.where(Reward.user_id == user_id)

        result = await session.exec(stmt)
        reward_entry = result.first()
        if not reward_entry:
            return None

        reward_entry.is_read = True
        reward_entry.updated_at = get_current_time()
        session.add(reward_entry)
        await session.commit()
        await session.refresh(reward_entry)
        logger.info(f"Reward {reward_id} marked as read")
        return reward_entry


    async def get_by_id(
        self,
        reward_id: str,
        session: Optional[AsyncSession] = None,
    ) -> Optional[Reward]:
        """
        Fetch a reward by ID.
        """
        sess = session or self.session
        if sess is not None:
            return await sess.get(Reward, reward_id)
        else:
            manager = get_mysql_manager()
            async with manager.session() as db_session:
                return await db_session.get(Reward, reward_id)


def get_reward_service(
    session: AsyncSession = Depends(get_async_session),
) -> RewardService:
    """FastAPI dependency provider for RewardService."""
    return RewardService(session)
