from src.core.utils import generate_uuid
import asyncio
from datetime import datetime, timedelta
import json
import logging
from typing import Dict, List, Optional, Any, Union
from starlette.websockets import WebSocketState
from fastapi import WebSocket

logger = logging.getLogger(__name__)

# Default duration for cached messages before they are cleared
CACHE_DURATION: timedelta = timedelta(minutes=2)


class WebSocketManager:
    """
    Streamlined WebSocket manager that maintains an in-memory dictionary
    mapping user_id -> WebSocket connection, providing simple send & broadcast functionality,
    along with message caching, message ID tracking, and periodic expiration cleanup.
    """

    def __init__(
        self,
        cache_duration: Optional[Union[timedelta, int, float]] = None,
        *args,
        **kwargs,
    ):
        # In-memory mapping: user_id (str) -> WebSocket
        self.connections: Dict[str, WebSocket] = {}
        # In-memory mapping: user_id (str) -> list of cached message dicts
        self.cached_messages: Dict[str, List[dict]] = {}
        # Alias for self.cached_messages
        self.message_cache: Dict[str, List[dict]] = self.cached_messages
        self.cache_duration: Union[timedelta, int, float] = (
            cache_duration if cache_duration is not None else CACHE_DURATION
        )
        self._cleanup_task: Optional[asyncio.Task] = None

    async def connect(
        self,
        websocket: WebSocket,
        user_id: str,
        **kwargs,
    ) -> bool:
        """Connect and register a user's WebSocket connection."""
        target_id = user_id
        if target_id is None:
            logger.error("connect requires a user_id or device_id")
            return False

        uid = target_id
        try:
            await websocket.accept()

            if uid in self.connections:
                old_ws = self.connections[uid]
                if old_ws != websocket:
                    try:
                        await old_ws.close()
                    except Exception:
                        pass

            self.connections[uid] = websocket
            logger.info(f"WebSocket connection registered for user_id: {uid}")

            # Ensure cleanup task is running if loop is active
            self.start_cleanup_task()

            # Forward the most recent cached message to the user if available and not expired
            cached_messages = self.cached_messages.get(uid)
            if cached_messages:
                most_recent_msg = cached_messages[-1]
                if not self.is_message_expired(most_recent_msg):
                    await self.send(uid, most_recent_msg, cache=False)

            return True
        except Exception as e:
            logger.error(f"Failed to connect user {uid}: {e}")
            return False

    async def disconnect(self, user_id: Any, reason: str = ""):
        """Disconnect and unregister a user's WebSocket connection."""
        uid = str(user_id)
        ws = self.connections.pop(uid, None)
        if ws:
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.close()
            except Exception as e:
                logger.warning(f"Error closing WebSocket for user {uid}: {e}")
        logger.info(f"WebSocket connection removed for user: {uid} ({reason})")

    async def send(
        self,
        user_id: Any,
        message: Any,
        cache: bool = True,
        **kwargs,
    ) -> bool:
        """
        Send a message to a specific user_id.
        The message dict should already include an 'id'; if None, it is assigned via message["id"] = generate_uuid().
        Any message sent is timestamped with datetime.now() attached to message["timestamp"] and cached for that user (unless cache=False).
        """
        uid = str(user_id)
        ws = self.connections.get(uid)
        if not ws:
            logger.debug(f"User {uid} not connected to WebSocket.")
            return False

        if ws.client_state != WebSocketState.CONNECTED:
            await self.disconnect(uid, reason="WebSocket disconnected")
            return False

        if hasattr(message, "model_dump") and callable(message.model_dump):
            message = message.model_dump()
        elif hasattr(message, "dict") and callable(message.dict):
            message = message.dict()

        if isinstance(message, dict):
            if message.get("id") is None:
                message["id"] = generate_uuid()

        try:
            if isinstance(message, str):
                text = message
            elif hasattr(message, "model_dump_json"):
                text = message.model_dump_json()
            elif hasattr(message, "json"):
                text = message.json()
            else:
                text = json.dumps(message, default=str)

            await ws.send_text(text)

            should_cache = kwargs.get("should_cache", kwargs.get("recache", cache))
            if should_cache:
                # Timestamp message with datetime.now() before adding to cache
                if isinstance(message, dict):
                    message["timestamp"] = datetime.now()
                    cached_entry = message
                else:
                    cached_entry = {"content": message, "timestamp": datetime.now()}

                if uid not in self.cached_messages:
                    self.cached_messages[uid] = []
                self.cached_messages[uid].append(cached_entry)
        
            return True
        except Exception as e:
            logger.error(f"Failed to send message to user {uid}: {e}")
            await self.disconnect(uid, reason="Send error")
            return False

    def remove_message_from_cache(self, user_id: Any, message_id: Any) -> bool:
        """
        Remove a message from cache for a specific user.
        Takes user_id and message_id and deletes that cache entry for that user.
        """
        uid = str(user_id)
        if uid not in self.cached_messages:
            return False

        initial_len = len(self.cached_messages[uid])
        self.cached_messages[uid] = [
            msg
            for msg in self.cached_messages[uid]
            if msg.get("id") != message_id and str(msg.get("id")) != str(message_id)
        ]
        return len(self.cached_messages[uid]) < initial_len

    # Aliases for removing a message from cache
    remove_from_cache = remove_message_from_cache
    remove_cached_message = remove_message_from_cache
    delete_cached_message = remove_message_from_cache

    def is_message_expired(
        self,
        msg: dict,
        cache_duration: Optional[Union[timedelta, int, float]] = None,
    ) -> bool:
        """Check if a cached message has expired according to cache_duration."""
        ts = msg.get("timestamp")
        if not ts:
            return False

        duration = (
            cache_duration
            if cache_duration is not None
            else self.cache_duration
        )
        now = datetime.now()

        if isinstance(ts, datetime):
            age = now - ts
            return (
                age >= duration
                if isinstance(duration, timedelta)
                else age.total_seconds() >= duration
            )
        elif isinstance(ts, str):
            try:
                dt = datetime.fromisoformat(ts)
                age = now - dt
                return (
                    age >= duration
                    if isinstance(duration, timedelta)
                    else age.total_seconds() >= duration
                )
            except Exception:
                return False
        return False

    def clear_expired_messages(
        self,
        cache_duration: Optional[Union[timedelta, int, float]] = None,
    ) -> int:
        """
        Periodically checks messages in the system across all users,
        and if it has been CACHE_DURATION since added, clears them.
        Returns the number of messages cleared.
        """
        duration = (
            cache_duration
            if cache_duration is not None
            else self.cache_duration
        )
        cleared_count = 0

        for uid in list(self.cached_messages.keys()):
            remaining = []
            for msg in self.cached_messages[uid]:
                if self.is_message_expired(msg, cache_duration=duration):
                    cleared_count += 1
                else:
                    remaining.append(msg)

            self.cached_messages[uid] = remaining

        return cleared_count

    # Aliases for clearing expired messages
    clean_expired_cache = clear_expired_messages
    clear_expired_cache = clear_expired_messages

    async def periodic_cache_cleanup(
        self,
        interval_seconds: float = 60.0 * 5, # Run every 5 minutes
        cache_duration: Optional[Union[timedelta, int, float]] = None,
    ):
        """
        Task that periodically checks messages in the system,
        and if it has been CACHE_DURATION since added, clears them.
        """
        while True:
            try:
                await asyncio.sleep(interval_seconds)
                self.clear_expired_messages(cache_duration=cache_duration)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in periodic cache cleanup task: {e}")

    def start_cleanup_task(
        self,
        interval_seconds: float = 60.0 * 5, #Run every 5 minutes
        cache_duration: Optional[Union[timedelta, int, float]] = None,
        restart: bool = False,
    ) -> Optional[asyncio.Task]:
        """Start the periodic background cleanup task."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            if self._cleanup_task and not self._cleanup_task.done():
                if restart or interval_seconds != (60.0 * 5) or cache_duration is not None:
                    self._cleanup_task.cancel()
                    self._cleanup_task = None

            if self._cleanup_task is None or self._cleanup_task.done():
                self._cleanup_task = loop.create_task(
                    self.periodic_cache_cleanup(
                        interval_seconds=interval_seconds,
                        cache_duration=cache_duration,
                    )
                )
            return self._cleanup_task
        return None

    async def stop_cleanup_task(self):
        """Stop the periodic background cleanup task."""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None

    def get_cached_messages(self, user_id: Any) -> List[dict]:
        """Return the list of cached messages for a user_id."""
        return self.cached_messages.get(str(user_id), [])

    async def broadcast(
        self,
        message: Any,
        user_ids: Optional[List[Any]] = None,
        exclude_user_id: Optional[Any] = None,
    ) -> int:
        """Broadcast a message to specified users or all connected users."""
        target_ids = (
            [str(u) for u in user_ids]
            if user_ids is not None
            else list(self.connections.keys())
        )
        if exclude_user_id is not None:
            exclude_str = str(exclude_user_id)
            target_ids = [u for u in target_ids if u != exclude_str]

        sent_count = 0
        for uid in target_ids:
            msg_copy = dict(message) if isinstance(message, dict) else message
            if await self.send(uid, msg_copy):
                sent_count += 1
        return sent_count

    def is_connected(self, user_id: Any) -> bool:
        return str(user_id) in self.connections

    def get_connected_user_ids(self) -> List[str]:
        return list(self.connections.keys())


async def periodic_cache_cleanup_task(
    manager: Optional[WebSocketManager] = None,
    interval_seconds: float = 60.0,
    cache_duration: Optional[Union[timedelta, int, float]] = None,
):
    """
    Periodic task that checks messages in the system,
    and if it has been CACHE_DURATION since added, clears them.
    """
    mgr = manager or websocket_manager
    await mgr.periodic_cache_cleanup(
        interval_seconds=interval_seconds,
        cache_duration=cache_duration,
    )


# Global singleton instance
websocket_manager = WebSocketManager()


def get_websocket_manager() -> WebSocketManager:
    return websocket_manager


