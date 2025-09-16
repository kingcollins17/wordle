# src/game/game_reward_manager.py
from typing import Optional
import random
import logging

from fastapi import Depends

from src.models.wordle_user import WordleUser
from src.database.mysql_connection_manager import (
    MySQLConnectionManager,
    get_mysql_manager,
)
from src.database.redis_service import RedisService, get_redis
from src.repositories.user_repository import UserRepository, get_user_repository

logger = logging.getLogger(__name__)

from pydantic import BaseModel


# ----------------------------
# Pydantic model for reward
# ----------------------------
class GameReward(BaseModel):
    coins: int = 0
    xp: int = 0
    reveal_letter: int = 0
    fish_out: int = 0
    ai_meaning: int = 0


# ----------------------------
# GameRewardManager
# ----------------------------
class GameRewardManager:

    def __init__(
        self,
        db: MySQLConnectionManager = Depends(get_mysql_manager),
        redis: RedisService = Depends(get_redis),
        user_repo: UserRepository = Depends(get_user_repository),
    ):
        self.db = db
        self.redis = redis
        self.user_repo = user_repo

    async def generate_reward(
        self,
        user: WordleUser,
        won: bool,
        attempts: int,
    ) -> GameReward:
        """
        Generate reward after a game.

        Args:
            user: The player
            won: Whether the user won
            attempts: Number of attempts taken to guess correctly (for scaling reward)

        Returns:
            GameReward object
        """

        # ----------------------------
        # Base coins and XP
        # ----------------------------
        base_coins = 50 if won else 20
        base_xp = 30 if won else 10

        # Scale coins based on attempts (fewer attempts = higher reward)
        if attempts > 0:
            coins_multiplier = max(0.5, 1.5 - 0.1 * (attempts - 1))
            xp_multiplier = max(0.5, 1.2 - 0.05 * (attempts - 1))
        else:
            coins_multiplier = 1
            xp_multiplier = 1

        coins = int(base_coins * coins_multiplier)
        xp = int(base_xp * xp_multiplier)

        # ----------------------------
        # Power-up reward chance
        # ----------------------------
        reveal_letter = 1 if random.random() < 0.2 else 0
        fish_out = 1 if random.random() < 0.2 else 0
        ai_meaning = 1 if random.random() < 0.2 else 0

        reward = GameReward(
            coins=coins,
            xp=xp,
            reveal_letter=reveal_letter,
            fish_out=fish_out,
            ai_meaning=ai_meaning,
        )

        logger.info(f"Generated reward for user {user.username}: {reward}")
        return reward

    async def claim_reward(self, user: WordleUser, reward: GameReward) -> WordleUser:
        """
        Apply the reward to the user's account.

        Args:
            user: The player receiving the reward
            reward: GameReward object to claim

        Returns:
            Updated WordleUser object
        """
        updates = {
            "coins": user.coins + reward.coins,
            "xp": user.xp + reward.xp,
            "reveal_letter": user.reveal_letter + reward.reveal_letter,
            "fish_out": user.fish_out + reward.fish_out,
            "ai_meaning": user.ai_meaning + reward.ai_meaning,
        }

        # Update user in DB and invalidate cache
        await self.user_repo.update_user_by_id(user.id, updates)

        # Return updated user object
        updated_user_data = await self.user_repo.get_user_by_id(user.id)
        return WordleUser(**updated_user_data)


# ----------------------------
# Dependency Injection
# ----------------------------
def get_game_reward_manager(
    db: MySQLConnectionManager = Depends(get_mysql_manager),
    redis: RedisService = Depends(get_redis),
    user_repo: UserRepository = Depends(get_user_repository),
) -> GameRewardManager:
    return GameRewardManager(db=db, redis=redis, user_repo=user_repo)
