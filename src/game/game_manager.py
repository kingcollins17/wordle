import asyncio
import logging
import random
import string
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from datetime import datetime, timedelta
from uuid import uuid4

from fastapi import Depends

from src.database.redis_service import RedisService, get_redis
from src.game.game_algorithm import *
from .websocket_manager import WebSocketManager, get_websocket_manager

# from src.models.game_session import *

from src.models import *

logger = logging.getLogger(__name__)


class GameError(Exception):
    """Custom exception for game-related errors"""

    pass


class GameManager:
    def __init__(
        self, redis_service: RedisService, websocket_manager: WebSocketManager
    ):
        self.redis = redis_service
        self.websocket_manager = websocket_manager
        self.active_games: Dict[str, GameSession] = {}  # session_id -> GameSession
        self.player_to_session: Dict[str, str] = {}  # device_id -> session_id

        self._session_locks: Dict[str, asyncio.Lock] = {}  # session_id -> asyncio.Lock

        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None

        # Redis keys
        self.GAME_SESSION_KEY_PREFIX = "game:session:"
        self.PLAYER_SESSION_KEY_PREFIX = "game:player:"
        self.ACTIVE_GAMES_KEY = "game:active_sessions"
        self.GAME_TIMER_KEY_PREFIX = "game:timer:"

    async def startup(self):
        """Initialize the game manager"""
        logger.info("Starting Game Manager...")

        # Start background cleanup task
        self._cleanup_task = asyncio.create_task(self._cleanup_expired_games())

        # Restore active games from Redis if any
        await self._restore_active_games()

        logger.info("Game Manager started successfully")

    async def shutdown(self):
        """Cleanup game manager"""
        logger.info("Shutting down Game Manager...")

        # Cancel background tasks
        if self._cleanup_task:
            self._cleanup_task.cancel()

        # End all active games
        session_ids = list(self.active_games.keys())
        for session_id in session_ids:
            await self.end_game(session_id, "server_shutdown")

        logger.info("Game Manager shutdown complete")

    async def create_game(
        self,
        player1_user: WordleUser,
        player2_user: WordleUser,
        player1_secret_words: List[str],
        player2_secret_words: List[str],
        settings: Optional[GameSettings] = None,
    ) -> GameSession:
        """Create a new game session between two players"""
        async with self._lock:
            if settings is None:
                settings = GameSettings()

            if len(player1_secret_words) != settings.rounds:
                raise GameError(f"Player 1 must provide {settings.rounds} secret words")
            if len(player2_secret_words) != settings.rounds:

                raise GameError(f"Player 2 must provide {settings.rounds} secret words")

            # Check if players are already in games (using device_id as key)
            if player1_user.device_id in list(self.player_to_session.keys()):
                raise GameError(
                    f"Player p1 {player1_user.username} is already in a game"
                )
            if player2_user.device_id in list(self.player_to_session.keys()):
                raise GameError(
                    f"Player p2 {player2_user.username} is already in a game"
                )

            for word in player1_secret_words:
                if len(word) != settings.word_length:
                    raise GameError(
                        f"Player 1 word '{word}' does not match word length {settings.word_length}"
                    )

            for word in player2_secret_words:
                if len(word) != settings.word_length:
                    raise GameError(
                        f"Player 2 word '{word}' does not match word length {settings.word_length}"
                    )

            # Generate session ID and select words
            # session_id = str(uuid4())
            session_id = "0fa16c0c-54f8-486b-9026-a57b72bf927e"

            # Create player info
            player1_info = PlayerInfo(
                player_id=player1_user.device_id,
                username=player1_user.username,
                role=PlayerRole.player1,
                secret_words=player1_secret_words,
                attempts=[],
            )

            player2_info = PlayerInfo(
                player_id=player2_user.device_id,
                username=player2_user.username,
                role=PlayerRole.player2,
                secret_words=player2_secret_words,
                attempts=[],
            )

            # Determine if bot is involved
            one_is_bot = player1_user.device_id.startswith(
                "bot_"
            ) or player2_user.device_id.startswith("bot_")

            current_turn = (
                PlayerRole.player1
                if one_is_bot
                else random.choice([PlayerRole.player1, PlayerRole.player2])
            )
            # Create game session
            game_session = GameSession(
                session_id=session_id,
                players={
                    player1_user.device_id: player1_info,
                    player2_user.device_id: player2_info,
                },
                game_state=GameState.waiting,
                current_turn=current_turn,
                settings=settings,
            )

            # Store in memory and Redis
            self.active_games[session_id] = game_session
            self.player_to_session[player1_user.device_id] = session_id
            self.player_to_session[player2_user.device_id] = session_id

            await self._save_game_to_redis(game_session)
            await self._update_player_session_mapping(
                player1_user.device_id, session_id
            )
            await self._update_player_session_mapping(
                player2_user.device_id, session_id
            )

            logger.info(
                f"Created game session {session_id} between {player1_user.username} and {player2_user.username}"
            )
            return game_session

    async def start_game(self, session_id: str) -> bool:
        """Start a game session"""
        if session_id not in self.active_games:
            raise GameError(f"Game session {session_id} not found")

        game_session = self.active_games[session_id]

        if game_session.game_state != GameState.waiting:
            raise GameError(f"Game {session_id} is not in waiting state")

        # Update game state
        game_session.game_state = GameState.in_progress
        game_session.turn_timer_expires_at = datetime.utcnow() + timedelta(
            seconds=game_session.settings.round_time_limit
        )
        # Save to Redis
        await self._update_game_session(game_session)

        # Notify players
        await self.broadcast_game_update(
            session_id,
            MessageType.INIT,
            game_session,
        )
        logger.info(f"Started game session {session_id}")
        return True

    async def _update_game_session(self, session: GameSession):
        """Safely update the game session state in memory and Redis using a lock"""
        lock = self._get_session_lock(session.session_id)

        async with lock:
            try:
                self.active_games[session.session_id] = session

                for player_id in session.players:
                    self.player_to_session[player_id] = session.session_id

                await self._save_game_to_redis(session)

                logger.info(f"Updated game session {session.session_id} successfully")
            except Exception as e:
                logger.error(f"Failed to update game session {session.session_id}: {e}")
                raise e

    async def play(
        self,
        session_id: str,
        player_id: str,
        guess: str,
    ):
        """Process a guess from a player"""

        if session_id not in self.active_games:
            raise GameError(f"Game session {session_id} not found")

        game_session = self.active_games[session_id]

        player_info = game_session.players[player_id]
        current_round = game_session.current_round

        opponent_id = self._get_opponent_id(game_session, player_id)
        opponent_info = game_session.players[opponent_id]

        if game_session.game_state != GameState.in_progress:
            await self.websocket_manager.send_to_device(
                device_id=player_id,
                message=WebSocketMessage(
                    type=MessageType.WAITING,
                    data=WaitingPayload(waiting_for=opponent_info.role),
                ),
            )
            return

        if game_session.current_turn != player_info.role:
            await self.websocket_manager.send_to_device(
                device_id=player_id,
                message=WebSocketMessage(
                    type=MessageType.INFO, data=InfoPayload(message="Not your turn")
                ),
            )
            return

        if player_id not in game_session.players.keys():
            raise GameError(f"Player {player_info.username} is not in this game")

        if len(guess) != game_session.settings.word_length:
            await self.websocket_manager.send_to_device(
                device_id=player_id,
                message=WebSocketMessage(
                    type=MessageType.INFO,
                    data=InfoPayload(
                        message=f"Guess length must be {game_session.settings.word_length}",
                    ),
                ),
            )
            return

        opponents_secret_word = opponent_info.secret_words[current_round - 1]

        result = self._evaluate_guess(
            guess,
            target_word=opponents_secret_word,
        )
        # update attempt state
        attempt = GuessAttempt(
            player_id=player_id,
            result=result,
            guess=guess,
        )
        player_info.attempts.append(attempt)

        if result.is_correct():
            player_info.score += 1
            if game_session.is_last_round():
                winner = (
                    player_info
                    if player_info.score > opponent_info.score
                    else opponent_info
                )
                await self.end_game(
                    session_id,
                    winner_id=winner.player_id,
                    reason=f"Player {winner.username} won",
                )
            else:

                game_session.next_turn()
                game_session.next_round()
                await self._update_game_session(game_session)
                await self.broadcast_game_update(
                    session_id,
                    MessageType.RESULT,
                    data=ResultPayload(
                        round_winner=player_id,
                        guess=guess,
                        result=attempt,
                    ),
                )

        else:
            game_session.next_turn()
            await self._update_game_session(game_session)

            await self.broadcast_game_update(
                session_id,
                MessageType.GUESS,
                data=GuessPayload(
                    attempt_result=attempt,
                    current_turn=game_session.current_turn,
                ),
            )

    async def end_game(
        self,
        session_id: str,
        winner_id: Optional[str] = None,
        reason: str = "manual",
    ) -> bool:
        """End a game session"""
        if session_id not in self.active_games:
            return False

        game_session = self.active_games[session_id]

        # Update game state
        game_session.game_state = GameState.game_over
        game_session.outcome = GameOutcome(
            winner_id=winner_id,
            reason=reason,
            completed_at=datetime.utcnow(),
        )

        # Notify players
        await self.broadcast_game_update(
            session_id,
            MessageType.GAME_OVER,
            data=GameOverPayload(
                winner_id=winner_id,
                reason=reason,
            ),
        )
        await self.websocket_manager.disconnect_all(list(game_session.players.keys()))
        # Clean up
        await self._cleanup_game_session(session_id)

        logger.info(f"Ended game session {session_id} - {reason}")
        return True

    async def get_game_session(self, session_id: str) -> Optional[GameSession]:
        """Get a game session by ID"""
        if session_id in self.active_games:
            print("game in active games")
            return self.active_games[session_id]

        # Try to load from Redis
        return await self._load_game_from_redis(session_id)

    async def get_player_game_session(self, player_id: str) -> Optional[GameSession]:
        """Get the game session a player is currently in"""
        async with self._lock:
            if player_id in list(self.player_to_session.keys()):
                session_id = self.player_to_session[player_id]
                return await self.get_game_session(session_id)
            return None

    def _get_session_lock(self, session_id: str) -> asyncio.Lock:
        """Get or create an asyncio.Lock for a session"""
        if session_id not in self._session_locks:
            self._session_locks[session_id] = asyncio.Lock()
        return self._session_locks[session_id]

    def _evaluate_guess(self, guess: str, target_word: str) -> GuessResult:
        """Evaluate a guess against the target word"""
        assert len(guess) == len(
            target_word
        ), f"Length of target and guess do not match {target_word} {guess}"
        return GameAlgorithm().evaluate_guess(target_word, guess)

    def _get_opponent_id(self, game_session: GameSession, player_id: str) -> str:
        """Get the opponent's ID"""
        player_ids = list(game_session.players.keys())
        return player_ids[0] if player_ids[1] == player_id else player_ids[1]

    async def broadcast_game_update(
        self,
        session_id: str,
        message_type: MessageType,
        data: Optional[Union[Dict, Any]] = None,
    ):
        """Broadcast game update to all players in the session"""
        if session_id not in self.active_games:
            return
        message = WebSocketMessage(type=message_type, data=data)
        game_session = self.active_games[session_id]
        devices = list(game_session.players.keys())
        # Broadcast to all devices in the game
        await self.websocket_manager.broadcast_to_devices(devices, message)

    async def _save_game_to_redis(self, game_session: GameSession):
        """Save game session to Redis"""
        try:
            await self.redis.set_json(
                f"{self.GAME_SESSION_KEY_PREFIX}{game_session.session_id}",
                game_session.model_dump(),
                expire_seconds=3600,  # 1 hour
            )

            await self.redis.add_to_set(self.ACTIVE_GAMES_KEY, game_session.session_id)
        except Exception as e:
            logger.error(f"Failed to save game {game_session.session_id} to Redis: {e}")

    async def _load_game_from_redis(self, session_id: str) -> Optional[GameSession]:
        """Load game session from Redis"""
        try:
            data = await self.redis.get_json(
                f"{self.GAME_SESSION_KEY_PREFIX}{session_id}"
            )
            if data:
                return GameSession(**data)
        except Exception as e:
            logger.error(f"Failed to load game {session_id} from Redis: {e}")
        return None

    async def _update_player_session_mapping(self, player_id: str, session_id: str):
        """Update player to session mapping in Redis"""
        try:
            await self.redis.set_json(
                f"{self.PLAYER_SESSION_KEY_PREFIX}{player_id}",
                {"session_id": session_id},
                expire_seconds=3600,
            )
        except Exception as e:
            logger.error(
                f"Failed to update player session mapping for {player_id}: {e}"
            )

    async def _cleanup_game_session(self, session_id: str):
        """Clean up a game session from memory and Redis"""
        if session_id not in self.active_games:
            return

        game_session = self.active_games[session_id]

        # Remove from memory mappings - only need to clean player_to_session now

        for player_id in list(game_session.players.keys()):
            self.player_to_session.pop(player_id, None)

        # Remove from active games
        self.active_games.pop(session_id, None)
        # Clean up Redis
        try:
            await self.redis.redis.delete(f"{self.GAME_SESSION_KEY_PREFIX}{session_id}")
            await self.redis.redis.delete(f"{self.GAME_TIMER_KEY_PREFIX}{session_id}")
            await self.redis.redis.srem(self.ACTIVE_GAMES_KEY, session_id)

            for player_id in game_session.players.keys():
                await self.redis.redis.delete(
                    f"{self.PLAYER_SESSION_KEY_PREFIX}{player_id}"
                )

        except Exception as e:
            logger.error(f"Failed to cleanup Redis data for game {session_id}: {e}")
            raise e

    async def _restore_active_games(self):
        """Restore active games from Redis on startup"""
        try:
            session_ids = await self.redis.get_set(self.ACTIVE_GAMES_KEY)

            for session_id in session_ids:
                game_session = await self._load_game_from_redis(session_id)
                if game_session:
                    # Only restore games that are not completed
                    if game_session.game_state != "completed":
                        self.active_games[session_id] = game_session

                        # Restore mappings - only need player_to_session now
                        for player_id in game_session.players.keys():
                            self.player_to_session[player_id] = session_id

                        logger.info(f"Restored game session {session_id}")
                    else:
                        # Clean up completed games
                        await self._cleanup_game_session(session_id)

        except Exception as e:
            logger.error(f"Failed to restore active games: {e}")

    async def _cleanup_expired_games(self):
        """Background task to clean up expired games"""
        while True:
            try:
                await asyncio.sleep(60)  # Check every minute

                current_time = datetime.utcnow()
                expired_sessions = []

                for session_id, game_session in list(self.active_games.items()):
                    # Check for expired turn timers
                    if (
                        game_session.turn_timer_expires_at
                        and current_time > game_session.turn_timer_expires_at
                        and game_session.game_state == "in_progress"
                    ):

                        # End game due to timeout
                        opponent_id = self._get_opponent_id(
                            game_session, game_session.current_turn
                        )
                        await self.end_game(session_id, opponent_id, "turn_timeout")

                    # Check for games that have been inactive too long
                    time_since_created = current_time - game_session.created_at
                    if time_since_created > timedelta(hours=2):  # 2 hour limit
                        expired_sessions.append(session_id)

                # Clean up expired sessions
                for session_id in expired_sessions:
                    await self.end_game(
                        session_id,
                        reason="session_expired",
                    )

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup task: {e}")


# Global game manager instance
_game_manager: Optional[GameManager] = None


async def get_game_manager(
    redis: RedisService = Depends(get_redis),
    websocket_manager: WebSocketManager = Depends(get_websocket_manager),
) -> GameManager:
    """Get the game manager instance"""
    global _game_manager
    if _game_manager is None:
        await _startup_game_manager(redis, websocket_manager)
    return _game_manager


async def _startup_game_manager(
    redis: RedisService, websocket_manager: WebSocketManager
):
    """Initialize game manager on startup"""
    global _game_manager
    if _game_manager is None:
        _game_manager = GameManager(redis, websocket_manager)
    await _game_manager.startup()
    logger.info("Game Manager initialized")


async def shutdown_game_manager():
    """Cleanup game manager on shutdown"""
    global _game_manager
    if _game_manager:
        await _game_manager.shutdown()
        _game_manager = None
        logger.info("Game Manager shutdown complete")
