import asyncio
import json
import logging
from starlette.websockets import WebSocketState
from typing import Dict, List, Optional, Any, Set
from datetime import datetime, timedelta
from fastapi import WebSocket, WebSocketDisconnect
from fastapi import Depends

from pydantic import BaseModel
from enum import Enum

from src.database.redis_service import RedisService, get_redis
from src.models import WordleUser, WebSocketMessage, MessageType

logger = logging.getLogger(__name__)


class ConnectionStatus(str, Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    IDLE = "idle"


class ConnectionInfo(BaseModel):
    device_id: str
    websocket: WebSocket
    user: Optional[WordleUser] = None
    status: ConnectionStatus = ConnectionStatus.CONNECTED
    connected_at: datetime
    last_heartbeat: datetime

    class Config:
        arbitrary_types_allowed = True


class CachedMessage(BaseModel):
    message: WebSocketMessage
    cached_at: datetime


class WebSocketManager:
    def __init__(self, redis_service: RedisService, cache_duration_seconds: int = 300):
        self.redis = redis_service
        self.connections: Dict[str, ConnectionInfo] = {}  # device_id -> ConnectionInfo
        self.message_cache: Dict[str, List[CachedMessage]] = (
            {}
        )  # device_id -> List[CachedMessage]
        self.cache_duration_seconds = cache_duration_seconds
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._cache_cleanup_task: Optional[asyncio.Task] = None

        # Redis keys
        self.ACTIVE_CONNECTIONS_KEY = "ws:active_connections"
        self.USER_STATUS_KEY_PREFIX = "ws:user_status:"

        self._excluded: Set[str] = {}

    async def startup(self):
        """Initialize the WebSocket manager"""
        logger.info("Starting WebSocket manager...")

        # Start background tasks
        self._heartbeat_task = asyncio.create_task(self._heartbeat_monitor())
        self._cleanup_task = asyncio.create_task(self._cleanup_stale_connections())
        self._cache_cleanup_task = asyncio.create_task(self._cleanup_expired_cache())

        # Clean up any stale Redis data from previous runs
        await self._cleanup_redis_data()

        logger.info("WebSocket manager started successfully")

    async def shutdown(self):
        """Cleanup WebSocket manager"""
        logger.info("Shutting down WebSocket manager...")

        # Cancel background tasks
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self._cleanup_task:
            self._cleanup_task.cancel()
        if self._cache_cleanup_task:
            self._cache_cleanup_task.cancel()

        # Disconnect all connections
        device_ids = list(self.connections.keys())
        for device_id in device_ids:
            await self.disconnect(device_id, reason="Server shutdown")

        # Clear message cache
        self.message_cache.clear()

        # Clean up Redis data
        await self._cleanup_redis_data()

        logger.info("WebSocket manager shutdown complete")

    async def connect(
        self, websocket: WebSocket, device_id: str, user: Optional[WordleUser] = None
    ) -> bool:
        """Accept a new WebSocket connection"""
        try:
            await websocket.accept()

            # If device already connected, disconnect the old connection
            if device_id in self.connections:
                await self._force_disconnect_device(
                    device_id, "New connection from same device"
                )

            # Create connection info
            now = datetime.utcnow()
            connection_info = ConnectionInfo(
                device_id=device_id,
                websocket=websocket,
                user=user,
                connected_at=now,
                last_heartbeat=now,
            )

            # Store connection
            self.connections[device_id] = connection_info

            # Update Redis
            await self._update_connection_in_redis(device_id, connection_info)

            # Send welcome message
            await self.send_to_device(
                device_id,
                WebSocketMessage(
                    type=MessageType.CONNECTED,
                    data={
                        "device_id": device_id,
                        "user": user.model_dump() if user else None,
                        "server_time": now.isoformat(),
                    },
                ),
            )

            # Send all cached messages for this device
            await self._send_cached_messages(device_id)

            logger.info(f"WebSocket connection established for device: {device_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to connect device {device_id}: {e}")
            return False

    async def refresh_connection(
        self,
        websocket: WebSocket,
        device_id: str,
        user: Optional[WordleUser] = None,
    ) -> bool:
        """Refresh an existing WebSocket connection without calling `accept()`"""
        try:
            # ✅ Abort if socket is disconnected
            if websocket.client_state != WebSocketState.CONNECTED:
                logger.warning(
                    f"Cannot refresh connection: WebSocket for {device_id} is not connected"
                )
                return False

            # If device already connected, disconnect the old connection
            if device_id in self.connections:
                await self._cleanup_connection(device_id, "Refreshing connection")

            now = datetime.utcnow()

            # Create new connection info
            connection_info = ConnectionInfo(
                device_id=device_id,
                websocket=websocket,
                user=user,
                connected_at=now,
                last_heartbeat=now,
            )

            # Store connection
            self.connections[device_id] = connection_info

            # Update Redis
            await self._update_connection_in_redis(device_id, connection_info)

            # Send all cached messages for this device
            await self._send_cached_messages(device_id)

            logger.info(f"WebSocket connection refreshed for device: {device_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to refresh connection for device {device_id}: {e}")
            return False

    async def disconnect(self, device_id: str, reason: str = "Client disconnect"):
        """Disconnect a WebSocket connection"""
        if device_id not in self.connections:
            return

        connection_info = self.connections[device_id]
        websocket = connection_info.websocket

        try:
            # ✅ Check if the WebSocket is already closed
            if websocket.client_state != WebSocketState.DISCONNECTED:
                # Notify about disconnection
                await self.send_to_device(
                    device_id,
                    WebSocketMessage(
                        type=MessageType.DISCONNECTED,
                        data={"reason": reason},
                    ),
                )
                # Close the WebSocket if still open
                await websocket.close()

        except Exception as e:
            logger.warning(f"Error during disconnect notification for {device_id}: {e}")

        # Clean up connection
        await self._cleanup_connection(device_id, reason)

    async def disconnect_all(
        self,
        device_ids: List[str],
        reason: str = "Server disconnect",
    ):
        """Disconnect multiple WebSocket connections concurrently"""
        await asyncio.gather(
            *(self.disconnect(device_id, reason) for device_id in device_ids)
        )

    async def _force_disconnect_device(self, device_id: str, reason: str):
        """Force disconnect a device without notification"""
        if device_id not in self.connections:
            return

        connection_info = self.connections[device_id]

        try:
            await connection_info.websocket.close()
        except Exception:
            pass

        await self._cleanup_connection(device_id, reason)

    async def _cleanup_connection(self, device_id: str, reason: str):
        """Clean up all traces of a connection"""
        if device_id not in self.connections:
            return

        # Remove from local mappings
        self.connections.pop(device_id, None)

        # Update Redis
        await self._remove_connection_from_redis(device_id)

        logger.info(f"Connection cleaned up for device {device_id}: {reason}")

    async def _can_send_to_device(self, device_id: str) -> bool:
        if device_id in self._excluded:
            return False
        if device_id.startswith("bot_"):
            return False
        return True

    async def send_to_device(self, device_id: str, message: WebSocketMessage) -> bool:
        """Send a message to a specific device or cache it if disconnected"""
        can_send = await self._can_send_to_device(device_id)
        if not can_send:
            return True

        # If device is not connected, cache the message
        if device_id not in list(self.connections.keys()):
            logger.info(f"Device {device_id} not connected, caching message")
            await self._cache_message(device_id, message)
            return True

        connection_info: Optional[ConnectionInfo] = self.connections.get(device_id)
        if not connection_info:
            await self._cleanup_connection(
                device_id, reason="connection info not found"
            )
            logger.error(f"Could not find a connection for device {device_id}")
            # Cache the message for when device reconnects
            await self._cache_message(device_id, message)
            return True

        websocket = connection_info.websocket

        if websocket.client_state == WebSocketState.DISCONNECTED:
            await self._cleanup_connection(device_id, reason="WebSocket already closed")
            logger.warning(
                f"WebSocket for device {device_id} already closed before send, caching message"
            )
            # Cache the message for when device reconnects
            await self._cache_message(device_id, message)
            return True

        try:
            await websocket.send_text(message.model_dump_json())
            await self.update_heartbeat(device_id)
            return True

        except WebSocketDisconnect:
            await self._cleanup_connection(
                device_id, "WebSocket disconnected during send"
            )
            # Cache the message for when device reconnects
            await self._cache_message(device_id, message)
            return True

        except Exception as e:
            logger.error(f"Failed to send message to device {device_id}: {e}")
            # Cache the message for when device reconnects
            await self._cache_message(device_id, message)
            return True

    async def _cache_message(self, device_id: str, message: WebSocketMessage):
        """Cache a message for a disconnected device"""
        cached_msg = CachedMessage(message=message, cached_at=datetime.utcnow())

        if device_id not in self.message_cache:
            self.message_cache[device_id] = []

        self.message_cache[device_id].append(cached_msg)
        logger.debug(
            f"Cached message for device {device_id}. Cache size: {len(self.message_cache[device_id])}"
        )

    async def _send_cached_messages(self, device_id: str):
        """Send all cached messages for a device and clear the cache"""
        if device_id not in self.message_cache:
            return

        cached_messages = self.message_cache[device_id]
        if not cached_messages:
            return

        logger.info(
            f"Sending {len(cached_messages)} cached messages to device {device_id}"
        )

        # Send each cached message
        for cached_msg in cached_messages:
            try:
                # Use the underlying websocket directly to avoid re-caching on failure
                connection_info = self.connections.get(device_id)
                if (
                    connection_info
                    and connection_info.websocket.client_state
                    == WebSocketState.CONNECTED
                ):
                    await connection_info.websocket.send_text(
                        cached_msg.message.model_dump_json()
                    )
                else:
                    logger.warning(
                        f"Device {device_id} disconnected while sending cached messages"
                    )
                    break
            except Exception as e:
                logger.error(
                    f"Failed to send cached message to device {device_id}: {e}"
                )
                break

        # Clear the cache for this device
        self.message_cache.pop(device_id, None)
        logger.info(f"Cleared message cache for device {device_id}")

    async def _cleanup_expired_cache(self):
        """Periodically clean up expired cached messages"""
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute

                now = datetime.utcnow()
                expired_devices = []

                for device_id, cached_messages in self.message_cache.items():
                    # Filter out expired messages
                    valid_messages = [
                        msg
                        for msg in cached_messages
                        if (now - msg.cached_at).total_seconds()
                        < self.cache_duration_seconds
                    ]

                    if len(valid_messages) != len(cached_messages):
                        removed_count = len(cached_messages) - len(valid_messages)
                        logger.info(
                            f"Removed {removed_count} expired messages for device {device_id}"
                        )

                    if valid_messages:
                        self.message_cache[device_id] = valid_messages
                    else:
                        expired_devices.append(device_id)

                # Remove devices with no valid cached messages
                for device_id in expired_devices:
                    self.message_cache.pop(device_id, None)
                    logger.debug(f"Cleared empty cache for device {device_id}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cache cleanup task: {e}")

    async def broadcast_to_devices(
        self,
        device_ids: List[str],
        message: WebSocketMessage,
    ) -> List[str]:
        """Broadcast a message to multiple devices. Returns list of successfully sent device_ids"""
        successful_sends = []

        for device_id in device_ids:
            if await self.send_to_device(device_id, message):
                successful_sends.append(device_id)

        return successful_sends

    async def update_heartbeat(self, device_id: str):
        """Update heartbeat for a device"""
        if device_id in self.connections:
            self.connections[device_id].last_heartbeat = datetime.utcnow()
            await self._update_connection_in_redis(
                device_id=device_id, connection_info=self.connections[device_id]
            )

    def is_device_connected(self, device_id: str) -> bool:
        """Check if a device is connected"""
        return device_id in self.connections

    def get_connection_info(self, device_id: str) -> Optional[ConnectionInfo]:
        """Get connection info for a device"""
        return self.connections.get(device_id)

    def get_connected_devices(self) -> List[str]:
        """Get all connected device IDs"""
        return list(self.connections.keys())

    def get_connected_device_count(self) -> int:
        """Get total number of connected devices"""
        return len(self.connections)

    def get_cached_message_count(self, device_id: str) -> int:
        """Get the number of cached messages for a device"""
        return len(self.message_cache.get(device_id, []))

    def get_all_cached_devices(self) -> List[str]:
        """Get all device IDs with cached messages"""
        return list(self.message_cache.keys())

    async def _update_connection_in_redis(
        self, device_id: str, connection_info: ConnectionInfo
    ):
        """Update connection information in Redis"""
        try:
            connection_data = {
                "device_id": device_id,
                "user_id": connection_info.user.id if connection_info.user else None,
                "status": connection_info.status.value,
                "connected_at": connection_info.connected_at.isoformat(),
                "last_heartbeat": connection_info.last_heartbeat.isoformat(),
            }

            await self.redis.set_json(
                f"{self.USER_STATUS_KEY_PREFIX}{device_id}",
                connection_data,
                expire_seconds=3600,  # 1 hour expiry
            )

            # Add to active connections set
            await self.redis.add_to_set(self.ACTIVE_CONNECTIONS_KEY, device_id)

        except Exception as e:
            logger.error(f"Failed to update connection in Redis for {device_id}: {e}")

    async def _remove_connection_from_redis(self, device_id: str):
        """Remove connection from Redis"""
        try:
            await self.redis.redis.delete(f"{self.USER_STATUS_KEY_PREFIX}{device_id}")
            await self.redis.redis.srem(self.ACTIVE_CONNECTIONS_KEY, device_id)
        except Exception as e:
            logger.error(f"Failed to remove connection from Redis for {device_id}: {e}")

    async def _heartbeat_monitor(self):
        """Monitor heartbeats and disconnect stale connections"""
        # TODO: Monitor heartbeat
        while False:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds

                now = datetime.utcnow()
                stale_devices = []

                for device_id, connection_info in self.connections.items():
                    if now - connection_info.last_heartbeat > timedelta(minutes=2):
                        stale_devices.append(device_id)

                for device_id in stale_devices:
                    await self.disconnect(device_id, "Heartbeat timeout")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in heartbeat monitor: {e}")

    async def _cleanup_stale_connections(self):
        """Periodic cleanup of stale Redis data"""
        while True:
            try:
                await asyncio.sleep(300)  # Run every 5 minutes

                # Get all active connections from Redis
                redis_connections = await self.redis.get_set(
                    self.ACTIVE_CONNECTIONS_KEY
                )

                # Remove connections that no longer exist locally
                for device_id in redis_connections:
                    if device_id not in self.connections:
                        await self._remove_connection_from_redis(device_id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup task: {e}")

    async def _cleanup_redis_data(self):
        """Clean up all WebSocket-related Redis data"""
        try:
            # Get all connection keys
            connection_keys = await self.redis.get_keys(
                f"{self.USER_STATUS_KEY_PREFIX}*"
            )

            # Delete all keys
            all_keys = connection_keys + [self.ACTIVE_CONNECTIONS_KEY]

            if all_keys:
                await self.redis.redis.delete(*all_keys)

            logger.info(f"Cleaned up {len(all_keys)} Redis keys")

        except Exception as e:
            logger.error(f"Failed to cleanup Redis data: {e}")


# Global WebSocket manager instance
_websocket_manager: Optional[WebSocketManager] = None


def _get_websocket_manager(redis_service: RedisService) -> WebSocketManager:
    """Get or create WebSocket manager singleton"""
    global _websocket_manager
    if _websocket_manager is None:
        _websocket_manager = WebSocketManager(redis_service, cache_duration_seconds=60)
    return _websocket_manager


async def startup_websocket_manager(redis_service: RedisService):
    """Initialize WebSocket manager on startup"""
    websocket_manager = _get_websocket_manager(redis_service)
    await websocket_manager.startup()
    logger.info("WebSocket manager initialized")


async def get_websocket_manager(
    redis: RedisService = Depends(get_redis),
) -> WebSocketManager:
    if _websocket_manager is None:
        raise ValueError(
            "WebsocketManger has not been initialized, did you forget to call startup_websocket_manager()?"
        )
    return _websocket_manager


async def shutdown_websocket_manager():
    """Cleanup WebSocket manager on shutdown"""
    global _websocket_manager
    if _websocket_manager:
        await _websocket_manager.shutdown()
        _websocket_manager = None
        logger.info("WebSocket manager shutdown complete")
