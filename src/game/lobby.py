import asyncio
from fastapi import WebSocket
from typing import Dict, List, Optional


class CustomLobby:
    def __init__(self, code: str):
        self.code = code
        self.players: Dict[str, WebSocket] = {}
        self.secret_words: Dict[str, str] = {}
        self.ready = asyncio.Event()

    def add_player(
        self,
        player_id: str,
        ws: WebSocket,
        secret_word: Optional[str] = None,
    ):
        self.players[player_id] = ws
        if secret_word:
            self.secret_words[player_id] = secret_word
        if len(self.players) == 2:
            self.ready.set()


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


_lobby_manager: Optional[LobbyManager] = None


def get_lobby_manager() -> LobbyManager:
    """Singleton initializer"""
    global _lobby_manager
    if _lobby_manager is None:

        _lobby_manager = LobbyManager()
    return _lobby_manager


def lobby_manager() -> LobbyManager:
    """Get Lobby Manager through dependency injection"""
    return get_lobby_manager()
