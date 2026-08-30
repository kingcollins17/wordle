import asyncio
import json
import logging
from typing import Optional, Dict, Any, List, AsyncGenerator
from contextlib import asynccontextmanager
import redis.asyncio as aioredis
from redis.asyncio.client import PubSub
from src.core.env import Environment, get_env, get_environment
from fastapi import Depends

logger = logging.getLogger(__name__)


class RedisService:
    """
    Fault-tolerant Redis service.
    If Redis is unavailable or unconfigured, operations fall back to safe no-op values
    without throwing exceptions or crashing the application.
    """

    def __init__(self, env: Environment):
        self.env = env
        self.redis: Optional[aioredis.Redis] = None
        self._connection_lock = asyncio.Lock()
        self._subscribers: Dict[str, PubSub] = {}

    async def connect(self) -> Optional[aioredis.Redis]:
        """Establish connection to Redis if available."""
        if not self.env.redis_url and not self.env.redis_host:
            logger.debug("Redis is not configured. Running without Redis.")
            return None

        if self.redis is None:
            async with self._connection_lock:
                if self.redis is None:
                    try:
                        redis_url = (
                            self.env.redis_url
                            or f"redis://{self.env.redis_host}:{self.env.redis_port}/{self.env.redis_db}"
                        )
                        client = aioredis.from_url(
                            redis_url,
                            decode_responses=True,
                            socket_keepalive=True,
                            socket_connect_timeout=2,
                            health_check_interval=30,
                        )
                        await client.ping()
                        self.redis = client
                        logger.info(f"Connected to Redis at {self.env.redis_host or redis_url}")
                    except Exception as e:
                        logger.warning(
                            f"Redis connection unavailable ({e}). App running without Redis cache."
                        )
                        self.redis = None
        return self.redis

    async def disconnect(self):
        """Close Redis connection and cleanup subscribers."""
        try:
            for channel, pubsub in list(self._subscribers.items()):
                try:
                    await pubsub.unsubscribe(channel)
                    await pubsub.close()
                except Exception as e:
                    logger.warning(f"Error closing subscriber for {channel}: {e}")

            self._subscribers.clear()

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
            if not redis:
                return False
            await redis.ping()
            return True
        except Exception as e:
            logger.warning(f"Redis health check failed: {e}")
            return False

    async def expire(self, key: str, seconds: int) -> bool:
        try:
            redis = await self.connect()
            if not redis:
                return False
            return await redis.expire(key, seconds)
        except Exception as e:
            logger.warning(f"Failed to set expiration for key {key}: {e}")
            return False

    async def get_keys(self, pattern: str = "*") -> List[str]:
        try:
            redis = await self.connect()
            if not redis:
                return []
            return await redis.keys(pattern)
        except Exception as e:
            logger.warning(f"Failed to get keys with pattern {pattern}: {e}")
            return []

    # JSON/Dict Methods
    async def set_json(
        self, key: str, data: Dict[str, Any], expire_seconds: Optional[int] = None
    ) -> bool:
        try:
            redis = await self.connect()
            if not redis:
                return False
            json_data = json.dumps(data, default=str)
            result = await redis.set(key, json_data, ex=expire_seconds)
            return bool(result)
        except Exception as e:
            logger.warning(f"Failed to store JSON data for key {key}: {e}")
            return False

    async def get_json(self, key: str) -> Optional[Dict[str, Any]]:
        try:
            redis = await self.connect()
            if not redis:
                return None
            data = await redis.get(key)
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            logger.warning(f"Failed to retrieve JSON data for key {key}: {e}")
            return None

    async def set_dict(
        self, key: str, data: Dict[str, Any], expire_seconds: Optional[int] = None
    ) -> bool:
        try:
            redis = await self.connect()
            if not redis:
                return False
            string_data = {
                k: json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                for k, v in data.items()
            }
            await redis.hset(key, mapping=string_data)
            if expire_seconds:
                await redis.expire(key, expire_seconds)
            return True
        except Exception as e:
            logger.warning(f"Failed to store hash data for key {key}: {e}")
            return False

    async def get_dict(self, key: str) -> Optional[Dict[str, Any]]:
        try:
            redis = await self.connect()
            if not redis:
                return None
            data = await redis.hgetall(key)
            if not data:
                return None

            parsed_data = {}
            for k, v in data.items():
                try:
                    parsed_data[k] = json.loads(v)
                except (json.JSONDecodeError, TypeError):
                    parsed_data[k] = v
            return parsed_data
        except Exception as e:
            logger.warning(f"Failed to retrieve hash data for key {key}: {e}")
            return None

    # Pub/Sub Methods
    async def publish(self, channel: str, message: Any) -> int:
        try:
            redis = await self.connect()
            if not redis:
                return 0
            if isinstance(message, (dict, list)):
                message = json.dumps(message, default=str)
            elif not isinstance(message, str):
                message = str(message)

            return await redis.publish(channel, message)
        except Exception as e:
            logger.warning(f"Failed to publish message to channel {channel}: {e}")
            return 0

    async def subscribe(self, channel: str) -> Optional[PubSub]:
        try:
            redis = await self.connect()
            if not redis:
                return None
            pubsub = redis.pubsub()
            await pubsub.subscribe(channel)
            self._subscribers[channel] = pubsub
            return pubsub
        except Exception as e:
            logger.warning(f"Failed to subscribe to channel {channel}: {e}")
            return None

    async def unsubscribe(self, channel: str) -> bool:
        try:
            if channel in self._subscribers:
                pubsub = self._subscribers[channel]
                await pubsub.unsubscribe(channel)
                await pubsub.close()
                del self._subscribers[channel]
                return True
            return False
        except Exception as e:
            logger.warning(f"Failed to unsubscribe from channel {channel}: {e}")
            return False

    @asynccontextmanager
    async def listen_to_channel(self, channel: str):
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
        async with self.listen_to_channel(channel) as pubsub:
            if pubsub:
                async for message in pubsub.listen():
                    if message["type"] == "message":
                        data = message["data"]
                        try:
                            parsed_data = json.loads(data)
                            yield {"channel": channel, "data": parsed_data, "raw": data}
                        except (json.JSONDecodeError, TypeError):
                            yield {"channel": channel, "data": data, "raw": data}

    # List operations
    async def push_to_list(self, key: str, *items: Any, left: bool = False) -> int:
        try:
            redis = await self.connect()
            if not redis:
                return 0
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
            logger.warning(f"Failed to push items to list {key}: {e}")
            return 0

    async def get_list(self, key: str, start: int = 0, end: int = -1) -> List[Any]:
        try:
            redis = await self.connect()
            if not redis:
                return []
            items = await redis.lrange(key, start, end)
            parsed_items = []
            for item in items:
                try:
                    parsed_items.append(json.loads(item))
                except (json.JSONDecodeError, TypeError):
                    parsed_items.append(item)
            return parsed_items
        except Exception as e:
            logger.warning(f"Failed to get list items for key {key}: {e}")
            return []

    # Set operations
    async def add_to_set(self, key: str, *items: Any) -> int:
        try:
            redis = await self.connect()
            if not redis:
                return 0
            string_items = []
            for item in items:
                if isinstance(item, (dict, list)):
                    string_items.append(json.dumps(item, default=str))
                else:
                    string_items.append(str(item))

            return await redis.sadd(key, *string_items)
        except Exception as e:
            logger.warning(f"Failed to add items to set {key}: {e}")
            return 0

    async def get_set(self, key: str) -> List[Any]:
        try:
            redis = await self.connect()
            if not redis:
                return []
            items = await redis.smembers(key)
            parsed_items = []
            for item in items:
                try:
                    parsed_items.append(json.loads(item))
                except (json.JSONDecodeError, TypeError):
                    parsed_items.append(item)
            return parsed_items
        except Exception as e:
            logger.warning(f"Failed to get set members for key {key}: {e}")
            return []


# Global Redis service instance
_redis_service: Optional[RedisService] = None


def _get_redis_service(env: Environment) -> RedisService:
    global _redis_service
    if _redis_service is None:
        _redis_service = RedisService(env)
    return _redis_service


def get_redis_or_none() -> Optional[RedisService]:
    return _redis_service


def get_redis(env: Environment = Depends(get_env)) -> RedisService:
    return _get_redis_service(env)


async def startup_redis(env: Environment):
    try:
        redis_service = _get_redis_service(env)
        await redis_service.connect()
    except Exception as e:
        logger.warning(f"Redis startup skipped/failed: {e}. App will continue without Redis.")


async def shutdown_redis():
    global _redis_service
    if _redis_service:
        await _redis_service.disconnect()
        _redis_service = None
        logger.info("Redis service shutdown complete")
