from fastapi import WebSocket
from typing import List, Tuple
import asyncio
import uuid
from src.models import *


class Match(BaseModel):
    player1: str  # player_id/device_id for player 1
    player2: str


class MatchmakingQueue:
    def __init__(self):
        self.queue: List[Tuple[str, WebSocket]] = []
        self.secret_words: dict[str, str] = {}

        """Completes wait_for_match method if a match has already been created by the second player"""
        self.pending_matches: dict[str, Match] = {}  # ✅ new

        self.lock = asyncio.Lock()

    async def add_player(
        self,
        player_id: str,
        ws: WebSocket,
        secret_word: str = None,
    ):
        async with self.lock:
            self.queue.append((player_id, ws))
            self.secret_words[player_id] = secret_word

    async def get_pair(self):
        async with self.lock:
            if len(self.queue) >= 2:
                return self.queue.pop(0), self.queue.pop(0)
            return None, None

    async def wait_for_match(
        self,
        player_id: str,
        timeout: int = 10,
    ) -> Optional[Match]:
        """
        Wait for a match for the specified player within the timeout period.

        Args:
            player_id: The ID of the player waiting for a match
            timeout: Maximum time to wait in seconds (default: 10)

        Returns:
            Match object if a match is found, None if timeout occurs
        """
        start_time = asyncio.get_event_loop().time()

        while True:
            # Check if we've exceeded the timeout
            current_time = asyncio.get_event_loop().time()
            if current_time - start_time >= timeout:
                return None

            async with self.lock:
                # ✅ Check for existing match
                match = self.pending_matches.get(player_id)
                if match:
                    # ✅ Remove once retrieved
                    self.pending_matches.pop(player_id)
                    return match

            # Try to get a pair from the queue
            async with self.lock:
                # Find if our player is in the queue and if there's at least one other player
                player_positions = []
                for i, (pid, ws) in enumerate(self.queue):
                    if pid == player_id:
                        player_positions.append(i)

                # If our player is in the queue and there are at least 2 players total
                if player_positions and len(self.queue) >= 2:
                    # Find the position of our player
                    our_position = player_positions[0]

                    # If we're first in queue, match with the second player
                    if our_position == 0 and len(self.queue) > 1:
                        player1_id, ws1 = self.queue.pop(0)  # Remove our player
                        player2_id, ws2 = self.queue.pop(0)  # Remove the next player

                        match = Match(player1=player1_id, player2=player2_id)
                        self._set_pending_match(player1_id, match)
                        return match

                    # If we're not first, wait for someone ahead of us to be matched
                    # or for us to move to the front
                    elif our_position > 0:
                        # Check if there's someone we can match with ahead of us
                        # (this handles the case where we're second and can match with first)
                        if our_position == 1:
                            player1_id, ws1 = self.queue.pop(
                                0
                            )  # Remove the first player
                            player2_id, ws2 = self.queue.pop(
                                0
                            )  # Remove our player (now at index 0)
                            match = Match(player1=player1_id, player2=player2_id)
                            self._set_pending_match(player1_id, match)
                            return match

            # Wait a short time before checking again
            await asyncio.sleep(0.1)

    def _set_pending_match(self, player_id: str, match: Match):
        """Set a pending match for the player."""

        self.pending_matches[player_id] = match

    # You'll also need to add the remove_player method that's used in the websocket handler:
    async def remove_player(self, player_id: str):
        """Remove a player from the matchmaking queue."""
        async with self.lock:
            self.queue = [(pid, ws) for pid, ws in self.queue if pid != player_id]
            self.secret_words.pop(
                player_id, None
            )  # Remove any secret word for this player


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
