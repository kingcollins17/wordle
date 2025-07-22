import asyncio
from fastapi import WebSocket
import logging
from typing import Dict, List, Optional

from src.game.websocket_manager import WebSocketManager
from src.models.game_session import GameSettings
from src.models.ws_models import MessageType, WebSocketMessage

logger = logging.getLogger(__name__)


class CustomLobby:
    def __init__(self, code: str):
        self.code = code
        self.players: Dict[str, WebSocket] = {}
        self.secret_words: Dict[str, List[str]] = {}
        self.settings: Optional[GameSettings] = None  # Game settings set by host
        self.host_id: Optional[str] = None  # The first player to join is the host
        self.ready = asyncio.Event()
        self.lock = asyncio.Lock()

    def add_player(
        self,
        player_id: str,
        ws: WebSocket,
        secret_words: Optional[List[str]] = None,
    ):
        self.players[player_id] = ws

        if not self.host_id:
            self.host_id = player_id  # First player becomes the host

        if secret_words:
            self.secret_words[player_id] = secret_words

        if len(self.players) == 2:
            self.ready.set()

    def is_host(self, player_id: str) -> bool:
        return self.host_id == player_id


class LobbyManager:
    def __init__(self):
        self.lobbies: Dict[str, CustomLobby] = {}

    def create_lobby(self, code: str) -> CustomLobby:
        lobby = CustomLobby(code)
        self.lobbies[code] = lobby
        return lobby

    def get_lobby(self, code: str) -> Optional[CustomLobby]:
        return self.lobbies.get(code)

    def remove_lobby(self, code: str):
        self.lobbies.pop(code, None)

    def generate_code(self) -> str:
        import random

        while True:
            code = str(random.randint(1000, 9999))
            if code not in self.lobbies:
                return code

    def get_lock(self, code: str) -> asyncio.Lock:
        """Safely get the lock for a given lobby code"""
        lobby = self.get_lobby(code)
        if not lobby:
            raise ValueError(f"Lobby {code} not found")
        return lobby.lock


# Singleton
_lobby_manager: Optional[LobbyManager] = None


def get_lobby_manager() -> LobbyManager:
    global _lobby_manager
    if _lobby_manager is None:
        _lobby_manager = LobbyManager()
    return _lobby_manager


def lobby_manager() -> LobbyManager:
    return get_lobby_manager()
