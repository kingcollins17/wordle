import json
import logging
from typing import Optional, List
from fastapi import Depends
from src.database.mysql_connection_manager import (
    MySQLConnectionManager,
    get_mysql_manager,
)
from src.database.query_manager import QueryManager
from ..models.challenges_models import *

logger = logging.getLogger(__name__)


class ChallengesRepository:
    def __init__(self, db: MySQLConnectionManager):
        self.db = db
        self.challenges_qm = QueryManager("challenges")

    async def create_challenge(self, challenge_data: ChallengeCreate) -> Challenge:
        """Create a new challenge"""
        try:
            dump = challenge_data.model_dump()
            dump["p1_secret_words"] = json.dumps(challenge_data.p1_secret_words)
            query, params = self.challenges_qm.insert(dump)
            challenge_id = await self.db.execute_query(query, params)

            created = await self.get_challenge_by_id(challenge_id)
            logger.info(
                f"Challenge created between {challenge_data.p1_username} and {challenge_data.p2_username}"
            )
            return created
        except Exception as e:
            logger.error(f"Error creating challenge: {e}")
            raise

    async def get_challenge_by_id(self, challenge_id: int) -> Optional[Challenge]:
        """Fetch a challenge by ID"""
        try:
            query, params = self.challenges_qm.select_one({"id": challenge_id})
            row = await self.db.execute_query(query, params, fetch="one")
            return Challenge(**row) if row else None
        except Exception as e:
            logger.error(f"Error fetching challenge {challenge_id}: {e}")
            raise

    async def get_challenge_by_lobby_code(self, lobby_code: str) -> Optional[Challenge]:
        """Fetch a challenge by its lobby code"""
        try:
            query, params = self.challenges_qm.select_one({"lobby_code": lobby_code})
            row = await self.db.execute_query(query, params, fetch="one")
            return Challenge(**row) if row else None
        except Exception as e:
            logger.error(f"Error fetching challenge with lobby_code={lobby_code}: {e}")
            raise

    async def update_challenge(
        self,
        challenge_id: int,
        update_data: ChallengeUpdate,
    ) -> Optional[Challenge]:
        """Update challenge secret words"""
        try:
            updates = update_data.model_dump(exclude_unset=True)

            # Convert secret words lists to JSON strings if present
            if "p1_secret_words" in updates and updates["p1_secret_words"] is not None:
                updates["p1_secret_words"] = json.dumps(updates["p1_secret_words"])
            if "p2_secret_words" in updates and updates["p2_secret_words"] is not None:
                updates["p2_secret_words"] = json.dumps(updates["p2_secret_words"])

            query, params = self.challenges_qm.update(
                updates=updates,
                where={"id": challenge_id},
            )
            affected = await self.db.execute_query(query, params)
            if affected > 0:
                updated = await self.get_challenge_by_id(challenge_id)
                return updated
            return None
        except Exception as e:
            logger.error(f"Error updating challenge {challenge_id}: {e}")
            raise

    async def delete_challenge(self, challenge_id: int) -> bool:
        """Delete a challenge"""
        try:
            query, params = self.challenges_qm.delete({"id": challenge_id})
            affected = await self.db.execute_query(query, params)
            return affected > 0
        except Exception as e:
            logger.error(f"Error deleting challenge {challenge_id}: {e}")
            raise

    async def list_challenges_for_user(
        self, user_id: int, limit: int = 50, offset: int = 0
    ) -> List[Challenge]:
        """List all challenges involving a user"""
        try:
            query = """
            SELECT * FROM challenges
            WHERE p1_id = %s OR p2_id = %s
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s
            """
            rows = await self.db.execute_query(
                query, [user_id, user_id, limit, offset], fetch="all"
            )
            return [Challenge(**row) for row in rows]
        except Exception as e:
            logger.error(f"Error listing challenges for user {user_id}: {e}")
            raise


def get_challenges_repository(mysql=Depends(get_mysql_manager)) -> ChallengesRepository:
    """Dependency injection for ChallengesRepository"""
    return ChallengesRepository(db=mysql)
