from fastapi import WebSocket
from typing import List, Tuple
import asyncio
import uuid
from src.models import *


class MatchmakingQueue:
    def __init__(self):
        self.queue: List[Tuple[str, WebSocket]] = []
        self.lock = asyncio.Lock()

    async def add_player(self, player_id: str, ws: WebSocket):
        async with self.lock:
            self.queue.append((player_id, ws))

    async def get_pair(self):
        async with self.lock:
            if len(self.queue) >= 2:
                return self.queue.pop(0), self.queue.pop(0)
            return None, None


# ✅ Shared instance of MatchmakingQueue
matchmaking_queue = MatchmakingQueue()


# ✅ Dependency provider
async def get_matchmaking_queue() -> MatchmakingQueue:
    return matchmaking_queue


async def matchmaking_loop():
    while True:
        p1, p2 = await matchmaking_queue.get_pair()
        if p1 and p2:
            player1_id, ws1 = p1
            player2_id, ws2 = p2
            game_id = str(uuid.uuid4())

            # Save session
            session = GameSession(...)
            # state.save_session(game_id, session)

            # # Notify players
            # await ws1.send_json(
            #     {"type": "matched", "data": {"game_id": game_id, "role": "player1"}}
            # )
            # await ws2.send_json(
            #     {"type": "matched", "data": {"game_id": game_id, "role": "player2"}}
            # )
        else:
            await asyncio.sleep(1)
