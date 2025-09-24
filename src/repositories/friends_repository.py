from typing import Optional, List, Dict, Any
import logging
from fastapi import Depends
from src.database.mysql_connection_manager import (
    MySQLConnectionManager,
    get_mysql_manager,
)
from src.database.redis_service import RedisService, get_redis
from src.database.query_manager import QueryManager
from src.models.friends_model import *
from ..models.wordle_user import WordleUser
from ..models.friend_request import *


logger = logging.getLogger(__name__)


class FriendsRepository:
    def __init__(self, db: MySQLConnectionManager, redis: RedisService):
        self.db = db
        self.redis = redis
        self.friend_requests_qm = QueryManager("friend_requests")
        self.friends_qm = QueryManager("friends")

    # -------------------------
    # Friend Requests
    # -------------------------

    async def create_friend_request(
        self, request_data: FriendRequestCreate
    ) -> FriendRequest:
        """Send a friend request"""
        try:
            query, params = self.friend_requests_qm.insert(request_data.dict())
            req_id = await self.db.execute_query(query, params)

            # Fetch the created request to return as model
            created_request = await self.get_friend_request_by_id(req_id)
            logger.info(
                f"Friend request created {request_data.sender_id} -> {request_data.receiver_id}"
            )
            return created_request
        except Exception as e:
            logger.error(f"Error creating friend request: {e}")
            raise

    async def get_friend_request_by_id(
        self, request_id: int
    ) -> Optional[FriendRequest]:
        """Get a friend request by ID"""
        try:
            query, params = self.friend_requests_qm.select_one({"id": request_id})
            row = await self.db.execute_query(query, params, fetch="one")
            return FriendRequest(**row) if row else None
        except Exception as e:
            logger.error(f"Error fetching friend request {request_id}: {e}")
            raise

    async def update_friend_request_status(
        self, request_id: int, update_data: FriendRequestUpdate
    ) -> Optional[FriendRequest]:
        """Update a friend request (accepted/declined)"""
        try:
            query, params = self.friend_requests_qm.update(
                updates=update_data.dict(exclude_unset=True), where={"id": request_id}
            )
            affected = await self.db.execute_query(query, params)

            if affected > 0:
                updated_request = await self.get_friend_request_by_id(request_id)
                logger.info(
                    f"Friend request {request_id} updated to {update_data.status}"
                )
                return updated_request
            return None
        except Exception as e:
            logger.error(f"Error updating friend request: {e}")
            raise

    async def list_friend_requests_received(
        self,
        user_id: int,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[FriendRequestWithSender]:
        """List friend requests received by a user with sender details"""
        try:
            query = """
            SELECT 
                fr.*,
                u.username AS sender_username,
                u.email AS sender_email,
                u.xp AS sender_xp,
                u.coins AS sender_coins
            FROM friend_requests fr
            JOIN users u ON fr.sender_id = u.id
            WHERE fr.receiver_id = %s
            """
            params = [user_id]

            if status:
                query += " AND fr.status = %s"
                params.append(status)

            query += " ORDER BY fr.created_at DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])

            rows = await self.db.execute_query(query, params, fetch="all")
            return [FriendRequestWithSender(**row) for row in rows]
        except Exception as e:
            logger.error(
                f"Error fetching received friend requests for user {user_id}: {e}"
            )
            raise

    async def list_friend_requests_sent(
        self,
        user_id: int,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[FriendRequestWithSender]:
        """List friend requests sent by a user with receiver details"""
        try:
            query = """
            SELECT 
                fr.*,
                u.username AS sender_username,
                u.email AS sender_email,
                u.xp AS sender_xp,
                u.coins AS sender_coins
            FROM friend_requests fr
            JOIN users u ON fr.receiver_id = u.id
            WHERE fr.sender_id = %s
            """
            params = [user_id]

            if status:
                query += " AND fr.status = %s"
                params.append(status)

            query += " ORDER BY fr.created_at DESC LIMIT %s OFFSET %s"
            print(query)
            params.extend([limit, offset])

            rows = await self.db.execute_query(query, params, fetch="all")
            # Note: For sent requests, the "sender" fields actually contain receiver data
            return [FriendRequestWithSender(**row) for row in rows]
        except Exception as e:
            logger.error(f"Error fetching sent friend requests for user {user_id}: {e}")
            raise

    async def list_all_friend_requests_with_details(
        self,
        user_id: int,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[FriendRequestWithDetails]:
        """List all friend requests (sent and received) with full details"""
        try:
            query = """
            SELECT 
                fr.*,
                sender.username AS sender_username,
                sender.email AS sender_email,
                sender.xp AS sender_xp,
                sender.coins AS sender_coins,
                receiver.username AS receiver_username,
                receiver.email AS receiver_email,
                receiver.xp AS receiver_xp,
                receiver.coins AS receiver_coins
            FROM friend_requests fr
            JOIN users sender ON fr.sender_id = sender.id
            JOIN users receiver ON fr.receiver_id = receiver.id
            WHERE (fr.sender_id = %s OR fr.receiver_id = %s)
            """
            params = [user_id, user_id]

            if status:
                query += " AND fr.status = %s"
                params.append(status)

            query += " ORDER BY fr.created_at DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])

            rows = await self.db.execute_query(query, params, fetch="all")
            return [FriendRequestWithDetails(**row) for row in rows]
        except Exception as e:
            logger.error(f"Error fetching all friend requests for user {user_id}: {e}")
            raise

    async def find_friend_request(
        self, sender_id: int, receiver_id: int
    ) -> Optional[FriendRequest]:
        """Check if a friend request already exists between two users"""
        try:
            query, params = self.friend_requests_qm.select_one(
                {"sender_id": sender_id, "receiver_id": receiver_id}
            )
            row = await self.db.execute_query(query, params, fetch="one")
            return FriendRequest(**row) if row else None
        except Exception as e:
            logger.error(f"Error finding friend request: {e}")
            raise

    async def find_mutual_friend_request(
        self, user1_id: int, user2_id: int
    ) -> Optional[FriendRequest]:
        """Find any friend request between two users (regardless of direction)"""
        try:
            query = """
            SELECT * FROM friend_requests
            WHERE (sender_id = %s AND receiver_id = %s)
               OR (sender_id = %s AND receiver_id = %s)
            LIMIT 1
            """
            params = [user1_id, user2_id, user2_id, user1_id]
            row = await self.db.execute_query(query, params, fetch="one")
            return FriendRequest(**row) if row else None
        except Exception as e:
            logger.error(f"Error finding mutual friend request: {e}")
            raise

    # -------------------------
    # Friends
    # -------------------------

    async def create_friendship(self, friendship_data: FriendCreate) -> Friend:
        """Create a friendship (should be called after request acceptance)"""
        try:
            query, params = self.friends_qm.insert(friendship_data.dict())
            friend_row_id = await self.db.execute_query(query, params)

            # Fetch the created friendship to return as model
            created_friendship = await self.get_friendship_by_id(friend_row_id)
            logger.info(
                f"Friendship created {friendship_data.user_id} <-> {friendship_data.friend_id}"
            )
            return created_friendship
        except Exception as e:
            logger.error(f"Error creating friendship: {e}")
            raise

    async def create_mutual_friendship(
        self, user1_id: int, user2_id: int
    ) -> List[Friend]:
        """Create mutual friendship (both directions)"""
        try:
            friendship1 = await self.create_friendship(
                FriendCreate(user_id=user1_id, friend_id=user2_id)
            )
            friendship2 = await self.create_friendship(
                FriendCreate(user_id=user2_id, friend_id=user1_id)
            )

            logger.info(f"Mutual friendship created between {user1_id} and {user2_id}")
            return [friendship1, friendship2]
        except Exception as e:
            logger.error(f"Error creating mutual friendship: {e}")
            raise

    async def get_friendship_by_id(self, friendship_id: int) -> Optional[Friend]:
        """Get a friendship by ID"""
        try:
            query, params = self.friends_qm.select_one({"id": friendship_id})
            row = await self.db.execute_query(query, params, fetch="one")
            return Friend(**row) if row else None
        except Exception as e:
            logger.error(f"Error fetching friendship {friendship_id}: {e}")
            raise

    async def list_friends_with_details(
        self, user_id: int, limit: int = 50, offset: int = 0
    ) -> List[FriendWithDetails]:
        """Fetch a user's friends with their full details and friendship date"""
        try:
            query = """
            SELECT 
                u.*,
                f.created_at AS friendship_created_at
            FROM friends f
            JOIN users u ON f.friend_id = u.id
            WHERE f.user_id = %s
            ORDER BY f.created_at DESC
            LIMIT %s OFFSET %s
            """
            rows = await self.db.execute_query(
                query, [user_id, limit, offset], fetch="all"
            )
            return [FriendWithDetails(**row) for row in rows]
        except Exception as e:
            logger.error(f"Error fetching friends with details for user {user_id}: {e}")
            raise

    async def list_friends(
        self, user_id: int, limit: int = 50, offset: int = 0
    ) -> List[WordleUser]:
        """Fetch a user's friends as basic user models"""
        try:
            query = """
            SELECT u.*
            FROM friends f
            JOIN users u ON f.friend_id = u.id
            WHERE f.user_id = %s
            ORDER BY f.created_at DESC
            LIMIT %s OFFSET %s
            """
            rows = await self.db.execute_query(
                query, [user_id, limit, offset], fetch="all"
            )
            return [WordleUser(**row) for row in rows]
        except Exception as e:
            logger.error(f"Error fetching friends for user {user_id}: {e}")
            raise

    async def get_friends_count(self, user_id: int) -> int:
        """Get the total count of friends for a user"""
        try:
            query = "SELECT COUNT(*) as count FROM friends WHERE user_id = %s"
            row = await self.db.execute_query(query, [user_id], fetch="one")
            return row["count"] if row else 0
        except Exception as e:
            logger.error(f"Error getting friends count for user {user_id}: {e}")
            raise

    async def are_friends(self, user_id: int, friend_id: int) -> bool:
        """Check if two users are friends"""
        try:
            query = """
            SELECT 1 FROM friends
            WHERE user_id = %s AND friend_id = %s
            LIMIT 1
            """
            row = await self.db.execute_query(query, [user_id, friend_id], fetch="one")
            return row is not None
        except Exception as e:
            logger.error(f"Error checking friendship {user_id}-{friend_id}: {e}")
            raise

    async def are_mutual_friends(self, user1_id: int, user2_id: int) -> bool:
        """Check if two users are mutual friends (both directions)"""
        try:
            query = """
            SELECT 1 FROM friends f1
            JOIN friends f2 ON f1.user_id = f2.friend_id AND f1.friend_id = f2.user_id
            WHERE f1.user_id = %s AND f1.friend_id = %s
            LIMIT 1
            """
            row = await self.db.execute_query(query, [user1_id, user2_id], fetch="one")
            return row is not None
        except Exception as e:
            logger.error(f"Error checking mutual friendship {user1_id}-{user2_id}: {e}")
            raise

    async def remove_friendship(self, user_id: int, friend_id: int) -> bool:
        """Remove a one-way friendship"""
        try:
            query, params = self.friends_qm.delete(
                {"user_id": user_id, "friend_id": friend_id}
            )
            affected = await self.db.execute_query(query, params)

            if affected > 0:
                logger.info(f"Friendship removed {user_id} -> {friend_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"Error removing friendship {user_id}-{friend_id}: {e}")
            raise

    async def remove_mutual_friendship(
        self, user1_id: int, user2_id: int
    ) -> Dict[str, bool]:
        """Remove mutual friendship (both directions)"""
        try:
            removed1 = await self.remove_friendship(user1_id, user2_id)
            removed2 = await self.remove_friendship(user2_id, user1_id)

            logger.info(
                f"Mutual friendship removal attempt between {user1_id} and {user2_id}"
            )
            return {"user1_to_user2": removed1, "user2_to_user1": removed2}
        except Exception as e:
            logger.error(f"Error removing mutual friendship: {e}")
            raise

    async def search_friends(
        self, user_id: int, search_term: str, limit: int = 20, offset: int = 0
    ) -> List[FriendWithDetails]:
        """Search friends by username or email"""
        try:
            search_pattern = f"%{search_term}%"
            query = """
            SELECT 
                u.*,
                f.created_at AS friendship_created_at
            FROM friends f
            JOIN users u ON f.friend_id = u.id
            WHERE f.user_id = %s 
            AND (u.username LIKE %s OR u.email LIKE %s)
            ORDER BY u.username
            LIMIT %s OFFSET %s
            """
            rows = await self.db.execute_query(
                query,
                [user_id, search_pattern, search_pattern, limit, offset],
                fetch="all",
            )
            return [FriendWithDetails(**row) for row in rows]
        except Exception as e:
            logger.error(f"Error searching friends for user {user_id}: {e}")
            raise

    async def get_mutual_friends(
        self, user1_id: int, user2_id: int, limit: int = 50, offset: int = 0
    ) -> List[WordleUser]:
        """Get mutual friends between two users"""
        try:
            query = """
            SELECT u.*
            FROM friends f1
            JOIN friends f2 ON f1.friend_id = f2.friend_id
            JOIN users u ON f1.friend_id = u.id
            WHERE f1.user_id = %s AND f2.user_id = %s
            ORDER BY u.username
            LIMIT %s OFFSET %s
            """
            rows = await self.db.execute_query(
                query, [user1_id, user2_id, limit, offset], fetch="all"
            )
            return [WordleUser(**row) for row in rows]
        except Exception as e:
            logger.error(
                f"Error fetching mutual friends for users {user1_id} and {user2_id}: {e}"
            )


def get_friends_repository(
    mysql=Depends(get_mysql_manager), redis=Depends(get_redis)
) -> FriendsRepository:
    """Dependency injection function for FriendsRepository"""
    return FriendsRepository(db=mysql, redis=redis)
