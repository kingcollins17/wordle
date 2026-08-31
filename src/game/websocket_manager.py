import json
import logging
from typing import Dict, List, Optional, Any
from starlette.websockets import WebSocketState
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketManager:
    """
    Streamlined WebSocket manager that maintains an in-memory dictionary
    mapping user_id -> WebSocket connection, providing simple send & broadcast functionality.
    """

    def __init__(self, *args, **kwargs):
        # In-memory mapping: user_id (str) -> WebSocket
        self.connections: Dict[str, WebSocket] = {}

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

    async def send(self, user_id: Any, message: Any) -> bool:
        """Send a message to a specific user_id."""
        uid = str(user_id)
        ws = self.connections.get(uid)
        if not ws:
            logger.debug(f"User {uid} not connected to WebSocket.")
            return False

        if ws.client_state != WebSocketState.CONNECTED:
            await self.disconnect(uid, reason="WebSocket disconnected")
            return False

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
            return True
        except Exception as e:
            logger.error(f"Failed to send message to user {uid}: {e}")
            await self.disconnect(uid, reason="Send error")
            return False


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
            if await self.send(uid, message):
                sent_count += 1
        return sent_count

    def is_connected(self, user_id: Any) -> bool:
        return str(user_id) in self.connections

    def get_connected_user_ids(self) -> List[str]:
        return list(self.connections.keys())

# Global singleton instance
websocket_manager = WebSocketManager()


def get_websocket_manager() -> WebSocketManager:
    return websocket_manager

