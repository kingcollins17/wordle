import asyncio
import json
import logging
from typing import Optional, Dict, Any, List, Callable, AsyncGenerator
from contextlib import asynccontextmanager
import redis.asyncio as aioredis
from redis.asyncio.client import PubSub
from src.core.env import Environment, get_env, get_environment
from fastapi import Depends

logger = logging.getLogger(__name__)


class RedisService:
    def __init__(self, env: Environment):
        self.env = env
        self.redis: Optional[aioredis.Redis] = None
        self._connection_lock = asyncio.Lock()
        self._subscribers: Dict[str, PubSub] = {}

    async def connect(self) -> aioredis.Redis:
        """Establish connection to Redis."""
        if self.redis is None:
            async with self._connection_lock:
                if self.redis is None:  # Double-check locking
                    try:
                        redis_url = f"redis://{self.env.redis_host}:{self.env.redis_port}/{self.env.redis_db}"
                        self.redis = aioredis.from_url(
                            redis_url,
                            decode_responses=True,
                            socket_keepalive=True,
                            socket_keepalive_options={},
                            health_check_interval=30,
                        )
                        # Test connection
                        await self.redis.ping()
                        logger.info(
                            f"Connected to Redis at {self.env.redis_host}:{self.env.redis_port}"
                        )
                    except Exception as e:
                        logger.error(f"Failed to connect to Redis: {e}")
                        raise
        return self.redis

    async def disconnect(self):
        """Close Redis connection and cleanup subscribers."""
        try:
            # Close all active subscribers
            for channel, pubsub in self._subscribers.items():
                try:
                    await pubsub.unsubscribe(channel)
                    await pubsub.close()
                except Exception as e:
                    logger.warning(f"Error closing subscriber for {channel}: {e}")

            self._subscribers.clear()

            # Close main connection
            if self.redis:
                await self.redis.close()
                self.redis = None
                logger.info("Redis connection closed")
        except Exception as e:
            logger.error(f"Error during Redis disconnect: {e}")

    async def health_check(self) -> bool:
        """Check Redis connection health."""
        try:
            redis = await self.connect()
            await redis.ping()
            return True
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            return False

    async def expire(self, key: str, seconds: int) -> bool:
        """Set expiration for a key."""
        try:
            redis = await self.connect()
            return await redis.expire(key, seconds)
        except Exception as e:
            logger.error(f"Failed to set expiration for key {key}: {e}")
            return False

    async def get_keys(self, pattern: str = "*") -> List[str]:
        """Get keys matching a pattern."""
        try:
            redis = await self.connect()
            return await redis.keys(pattern)
        except Exception as e:
            logger.error(f"Failed to get keys with pattern {pattern}: {e}")
            return []

    # JSON/Dict Methods
    async def set_json(
        self, key: str, data: Dict[str, Any], expire_seconds: Optional[int] = None
    ) -> bool:
        """Store a dictionary as JSON in Redis."""
        try:
            redis = await self.connect()
            json_data = json.dumps(data, default=str)
            result = await redis.set(key, json_data, ex=expire_seconds)
            logger.debug(f"Stored JSON data for key {key}")
            return result
        except Exception as e:
            logger.error(f"Failed to store JSON data for key {key}: {e}")
            return False

    async def get_json(self, key: str) -> Optional[Dict[str, Any]]:
        """Retrieve and parse JSON data from Redis."""
        try:
            redis = await self.connect()
            data = await redis.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.error(f"Failed to retrieve JSON data for key {key}: {e}")
            return None

    async def set_dict(
        self, key: str, data: Dict[str, Any], expire_seconds: Optional[int] = None
    ) -> bool:
        """Store a dictionary as a Redis hash."""
        try:
            redis = await self.connect()
            # Convert all values to strings for Redis hash storage
            string_data = {
                k: json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                for k, v in data.items()
            }
            result = await redis.hset(key, mapping=string_data)
            if expire_seconds:
                await redis.expire(key, expire_seconds)
            logger.debug(f"Stored hash data for key {key}")
            return True
        except Exception as e:
            logger.error(f"Failed to store hash data for key {key}: {e}")
            return False

    async def get_dict(self, key: str) -> Optional[Dict[str, Any]]:
        """Retrieve a Redis hash as a dictionary."""
        try:
            redis = await self.connect()
            data = await redis.hgetall(key)
            if not data:
                return None

            # Attempt to parse JSON values back to their original types
            parsed_data = {}
            for k, v in data.items():
                try:
                    parsed_data[k] = json.loads(v)
                except (json.JSONDecodeError, TypeError):
                    parsed_data[k] = v
            return parsed_data
        except Exception as e:
            logger.error(f"Failed to retrieve hash data for key {key}: {e}")
            return None

    # Pub/Sub Methods
    async def publish(self, channel: str, message: Any) -> int:
        """Publish a message to a Redis channel."""
        try:
            redis = await self.connect()
            if isinstance(message, (dict, list)):
                message = json.dumps(message, default=str)
            elif not isinstance(message, str):
                message = str(message)

            subscribers = await redis.publish(channel, message)
            logger.debug(
                f"Published message to channel {channel}, reached {subscribers} subscribers"
            )
            return subscribers
        except Exception as e:
            logger.error(f"Failed to publish message to channel {channel}: {e}")
            return 0

    async def subscribe(self, channel: str) -> PubSub:
        """Subscribe to a Redis channel and return the PubSub object."""
        try:
            redis = await self.connect()
            pubsub = redis.pubsub()
            await pubsub.subscribe(channel)

            # Store the subscriber for cleanup
            self._subscribers[channel] = pubsub
            logger.info(f"Subscribed to channel {channel}")
            return pubsub
        except Exception as e:
            logger.error(f"Failed to subscribe to channel {channel}: {e}")
            raise

    async def unsubscribe(self, channel: str) -> bool:
        """Unsubscribe from a Redis channel."""
        try:
            if channel in self._subscribers:
                pubsub = self._subscribers[channel]
                await pubsub.unsubscribe(channel)
                await pubsub.close()
                del self._subscribers[channel]
                logger.info(f"Unsubscribed from channel {channel}")
                return True
            else:
                logger.warning(f"No active subscription found for channel {channel}")
                return False
        except Exception as e:
            logger.error(f"Failed to unsubscribe from channel {channel}: {e}")
            return False

    @asynccontextmanager
    async def listen_to_channel(self, channel: str):
        """Context manager for subscribing to a channel and automatically cleaning up."""
        pubsub = None
        try:
            pubsub = await self.subscribe(channel)
            yield pubsub
        finally:
            if pubsub:
                await self.unsubscribe(channel)

    async def get_message_stream(
        self, channel: str
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Get an async generator that yields messages from a channel."""
        async with self.listen_to_channel(channel) as pubsub:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    data = message["data"]
                    # Try to parse JSON messages
                    try:
                        parsed_data = json.loads(data)
                        yield {"channel": channel, "data": parsed_data, "raw": data}
                    except (json.JSONDecodeError, TypeError):
                        yield {"channel": channel, "data": data, "raw": data}

    # List operations
    async def push_to_list(self, key: str, *items: Any, left: bool = False) -> int:
        """Push items to a Redis list."""
        try:
            redis = await self.connect()
            # Convert items to JSON strings if they're dicts/lists
            string_items = []
            for item in items:
                if isinstance(item, (dict, list)):
                    string_items.append(json.dumps(item, default=str))
                else:
                    string_items.append(str(item))

            if left:
                return await redis.lpush(key, *string_items)
            else:
                return await redis.rpush(key, *string_items)
        except Exception as e:
            logger.error(f"Failed to push items to list {key}: {e}")
            return 0

    async def get_list(self, key: str, start: int = 0, end: int = -1) -> List[Any]:
        """Get items from a Redis list."""
        try:
            redis = await self.connect()
            items = await redis.lrange(key, start, end)

            # Try to parse JSON items back to their original types
            parsed_items = []
            for item in items:
                try:
                    parsed_items.append(json.loads(item))
                except (json.JSONDecodeError, TypeError):
                    parsed_items.append(item)
            return parsed_items
        except Exception as e:
            logger.error(f"Failed to get list items for key {key}: {e}")
            return []

    # Set operations
    async def add_to_set(self, key: str, *items: Any) -> int:
        """Add items to a Redis set."""
        try:
            redis = await self.connect()
            # Convert items to JSON strings if they're dicts/lists
            string_items = []
            for item in items:
                if isinstance(item, (dict, list)):
                    string_items.append(json.dumps(item, default=str))
                else:
                    string_items.append(str(item))

            return await redis.sadd(key, *string_items)
        except Exception as e:
            logger.error(f"Failed to add items to set {key}: {e}")
            return 0

    async def get_set(self, key: str) -> List[Any]:
        """Get all members of a Redis set."""
        try:
            redis = await self.connect()
            items = await redis.smembers(key)

            # Try to parse JSON items back to their original types
            parsed_items = []
            for item in items:
                try:
                    parsed_items.append(json.loads(item))
                except (json.JSONDecodeError, TypeError):
                    parsed_items.append(item)
            return parsed_items
        except Exception as e:
            logger.error(f"Failed to get set members for key {key}: {e}")
            return []


# Global Redis service instance
_redis_service: Optional[RedisService] = None


def _get_redis_service(env: Environment) -> RedisService:
    """Get or create Redis service singleton."""
    global _redis_service
    if _redis_service is None:
        _redis_service = RedisService(env)
    return _redis_service


def get_redis_or_none() -> Optional[RedisService]:
    return _redis_service


def get_redis(env: Environment = Depends(get_env)) -> RedisService:
    return _get_redis_service(env)


async def startup_redis(env: Environment):
    """Initialize Redis service on startup."""
    redis_service = _get_redis_service(env)
    await redis_service.connect()
    logger.info("Redis service initialized")


async def shutdown_redis():
    """Cleanup Redis service on shutdown."""
    global _redis_service
    if _redis_service:
        await _redis_service.disconnect()
        _redis_service = None
        logger.info("Redis service shutdown complete")
