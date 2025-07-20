from typing import Optional, List, Dict, Any
import logging
from src.database.mysql_connection_manager import MySQLConnectionManager
from src.database.redis_service import RedisService
from src.database.query_manager import QueryManager  # Assumes you saved it separately
from ..models.wordle_user import WordleUser  # Your Pydantic model

logger = logging.getLogger(__name__)


class UserRepository:
    def __init__(self, db: MySQLConnectionManager, redis: RedisService):
        self.db = db
        self.redis = redis
        self.qm = QueryManager("users")
        # Redis cache configuration
        self.cache_ttl = 3600  # 1 hour cache TTL
        self.cache_prefix = "user"

    def _get_cache_key(self, field: str, value: str) -> str:
        """Generate Redis cache key for user data."""
        return f"{self.cache_prefix}:{field}:{value}"

    async def _get_user_from_cache(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """Get user data from Redis cache."""
        try:
            cached_user = await self.redis.get_json(cache_key)
            if cached_user:
                logger.debug(f"Cache hit for key: {cache_key}")
                return cached_user
            logger.debug(f"Cache miss for key: {cache_key}")
            return None
        except Exception as e:
            logger.warning(f"Redis cache read error for key {cache_key}: {e}")
            return None

    async def _cache_user(self, cache_key: str, user_data: Dict[str, Any]) -> None:
        """Store user data in Redis cache."""
        try:
            await self.redis.set_json(
                cache_key, user_data, expire_seconds=self.cache_ttl
            )
            logger.debug(f"Cached user data for key: {cache_key}")
        except Exception as e:
            logger.warning(f"Redis cache write error for key {cache_key}: {e}")

    async def _invalidate_user_cache(self, user_data: Dict[str, Any]) -> None:
        """Invalidate all cache entries for a user."""
        try:
            cache_keys = []

            # Generate all possible cache keys for this user
            if "device_id" in user_data:
                cache_keys.append(
                    self._get_cache_key("device_id", user_data["device_id"])
                )
            if "username" in user_data:
                cache_keys.append(
                    self._get_cache_key("username", user_data["username"])
                )
            if "id" in user_data:
                cache_keys.append(self._get_cache_key("id", str(user_data["id"])))

            # Delete all cache keys
            redis_client = await self.redis.connect()
            if cache_keys:
                await redis_client.delete(*cache_keys)
                logger.debug(f"Invalidated cache keys: {cache_keys}")
        except Exception as e:
            logger.warning(f"Cache invalidation error: {e}")

    async def get_user_by_device_id(self, device_id: str) -> Optional[Dict[str, Any]]:
        """Get user by device_id with Redis caching."""
        cache_key = self._get_cache_key("device_id", device_id)

        # Try cache first
        cached_user = await self._get_user_from_cache(cache_key)
        if cached_user:
            return cached_user

        # Cache miss - query database
        try:
            query, params = self.qm.select_one({"device_id": device_id})
            user_data = await self.db.execute_query(query, params, fetch="one")

            if user_data:
                # Cache the result before returning
                await self._cache_user(cache_key, user_data)

                # Also cache by other unique fields if present
                if "username" in user_data and user_data["username"]:
                    username_key = self._get_cache_key(
                        "username", user_data["username"]
                    )
                    await self._cache_user(username_key, user_data)
                if "id" in user_data:
                    id_key = self._get_cache_key("id", str(user_data["id"]))
                    await self._cache_user(id_key, user_data)

                logger.info(
                    f"User found in database and cached for device_id: {device_id}"
                )

            return user_data
        except Exception as e:
            logger.error(f"Database query error for device_id {device_id}: {e}")
            raise

    async def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """Get user by username with Redis caching."""
        cache_key = self._get_cache_key("username", username)

        # Try cache first
        cached_user = await self._get_user_from_cache(cache_key)
        if cached_user:
            return cached_user

        # Cache miss - query database
        try:
            query, params = self.qm.select_one({"username": username})
            user_data = await self.db.execute_query(query, params, fetch="one")

            if user_data:
                # Cache the result before returning
                await self._cache_user(cache_key, user_data)

                # Also cache by other unique fields if present
                if "device_id" in user_data and user_data["device_id"]:
                    device_id_key = self._get_cache_key(
                        "device_id", user_data["device_id"]
                    )
                    await self._cache_user(device_id_key, user_data)
                if "id" in user_data:
                    id_key = self._get_cache_key("id", str(user_data["id"]))
                    await self._cache_user(id_key, user_data)

                logger.info(
                    f"User found in database and cached for username: {username}"
                )

            return user_data
        except Exception as e:
            logger.error(f"Database query error for username {username}: {e}")
            raise

    async def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Get user by ID with Redis caching."""
        cache_key = self._get_cache_key("id", str(user_id))

        # Try cache first
        cached_user = await self._get_user_from_cache(cache_key)
        if cached_user:
            return cached_user

        # Cache miss - query database
        try:
            query, params = self.qm.select_one({"id": user_id})
            user_data = await self.db.execute_query(query, params, fetch="one")

            if user_data:
                # Cache the result before returning
                await self._cache_user(cache_key, user_data)

                # Also cache by other unique fields if present
                if "device_id" in user_data and user_data["device_id"]:
                    device_id_key = self._get_cache_key(
                        "device_id", user_data["device_id"]
                    )
                    await self._cache_user(device_id_key, user_data)
                if "username" in user_data and user_data["username"]:
                    username_key = self._get_cache_key(
                        "username", user_data["username"]
                    )
                    await self._cache_user(username_key, user_data)

                logger.info(f"User found in database and cached for user_id: {user_id}")

            return user_data
        except Exception as e:
            logger.error(f"Database query error for user_id {user_id}: {e}")
            raise

    async def create_user(self, user_data: Dict[str, Any]) -> int:
        """Create a new user and return the user ID."""
        try:
            query, params = self.qm.insert(user_data)
            user_id = await self.db.execute_query(query, params)

            # Add the user_id to the user_data for caching
            user_data_with_id = {**user_data, "id": user_id}

            # Cache the new user by all unique fields
            if "device_id" in user_data_with_id and user_data_with_id["device_id"]:
                device_id_key = self._get_cache_key(
                    "device_id", user_data_with_id["device_id"]
                )
                await self._cache_user(device_id_key, user_data_with_id)

            if "username" in user_data_with_id and user_data_with_id["username"]:
                username_key = self._get_cache_key(
                    "username", user_data_with_id["username"]
                )
                await self._cache_user(username_key, user_data_with_id)

            id_key = self._get_cache_key("id", str(user_id))
            await self._cache_user(id_key, user_data_with_id)

            logger.info(f"User created and cached with ID: {user_id}")
            return user_id
        except Exception as e:
            logger.error(f"User creation error: {e}")
            raise

    async def update_user_by_device_id(
        self, device_id: str, updates: Dict[str, Any]
    ) -> int:
        """Update user by device_id and invalidate cache."""
        try:
            # Get the current user data before update for cache invalidation
            current_user = await self.get_user_by_device_id(device_id)

            # Perform the update
            query, params = self.qm.update(
                updates=updates, where={"device_id": device_id}
            )
            affected_rows = await self.db.execute_query(query, params)

            # Invalidate cache for the user
            if current_user:
                await self._invalidate_user_cache(current_user)
                logger.info(f"Cache invalidated for user with device_id: {device_id}")

            return affected_rows
        except Exception as e:
            logger.error(f"User update error for device_id {device_id}: {e}")
            raise

    async def update_user_by_id(self, user_id: int, updates: Dict[str, Any]) -> int:
        """Update user by ID and invalidate cache."""
        try:
            # Get the current user data before update for cache invalidation
            current_user = await self.get_user_by_id(user_id)

            # Perform the update
            query, params = self.qm.update(updates=updates, where={"id": user_id})
            affected_rows = await self.db.execute_query(query, params)

            # Invalidate cache for the user
            if current_user:
                await self._invalidate_user_cache(current_user)
                logger.info(f"Cache invalidated for user with ID: {user_id}")

            return affected_rows
        except Exception as e:
            logger.error(f"User update error for user_id {user_id}: {e}")
            raise

    async def delete_user_by_device_id(self, device_id: str) -> int:
        """Delete user by device_id and invalidate cache."""
        try:
            # Get the current user data before deletion for cache invalidation
            current_user = await self.get_user_by_device_id(device_id)

            # Perform the deletion
            query, params = self.qm.delete(where={"device_id": device_id})
            affected_rows = await self.db.execute_query(query, params)

            # Invalidate cache for the user
            if current_user:
                await self._invalidate_user_cache(current_user)
                logger.info(
                    f"Cache invalidated for deleted user with device_id: {device_id}"
                )

            return affected_rows
        except Exception as e:
            logger.error(f"User deletion error for device_id {device_id}: {e}")
            raise

    async def list_users(
        self, filters: Optional[Dict[str, Any]] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """List users (not cached due to complexity of cache invalidation for lists)."""
        try:
            query, params = self.qm.select_many(where=filters, limit=limit)
            return await self.db.execute_query(query, params, fetch="all")
        except Exception as e:
            logger.error(f"User list query error: {e}")
            raise

    async def clear_user_cache(
        self,
        device_id: Optional[str] = None,
        username: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> None:
        """Manually clear cache for a specific user."""
        try:
            cache_keys = []

            if device_id:
                cache_keys.append(self._get_cache_key("device_id", device_id))
            if username:
                cache_keys.append(self._get_cache_key("username", username))
            if user_id:
                cache_keys.append(self._get_cache_key("id", str(user_id)))

            if cache_keys:
                redis_client = await self.redis.connect()
                await redis_client.delete(*cache_keys)
                logger.info(f"Manually cleared cache keys: {cache_keys}")
        except Exception as e:
            logger.warning(f"Manual cache clear error: {e}")

    async def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics for monitoring."""
        try:
            redis_client = await self.redis.connect()
            pattern = f"{self.cache_prefix}:*"
            keys = await redis_client.keys(pattern)

            return {
                "total_cached_users": len(keys),
                "cache_prefix": self.cache_prefix,
                "cache_ttl": self.cache_ttl,
                "cache_pattern": pattern,
            }
        except Exception as e:
            logger.error(f"Cache stats error: {e}")
            return {"error": str(e)}
