# bot/bot_player.py
import asyncio
import logging
import random
from datetime import datetime
from typing import Optional, List
from abc import ABC, abstractmethod

from fastapi import Depends, WebSocket
from fastapi.websockets import WebSocketState

from src.database.redis_service import get_redis
from src.game.game_manager import GameManager
from src.models import WordleUser, PlayerRole, GuessResult
from src.models.game_session import *

logger = logging.getLogger(__name__)


class BotStrategy(ABC):
    """Abstract base class for bot strategies"""

    @abstractmethod
    async def make_guess(
        self,
        word_length: int,
        previous_attempts: List[GuessResult],
        available_words: Optional[List[str]] = None,
    ) -> str:
        """Generate a guess based on the strategy"""
        pass


class RandomBotStrategy(BotStrategy):
    """Simple random guessing strategy"""

    def __init__(self, word_list: List[str]):
        self.word_list = word_list
        self.used_words = set()

    async def make_guess(
        self,
        word_length: int,
        previous_attempts: List[GuessResult],
        available_words: Optional[List[str]] = None,
    ) -> str:
        available = available_words or [
            word
            for word in self.word_list
            if len(word) == word_length and word not in self.used_words
        ]

        if not available:
            available = [word for word in self.word_list if len(word) == word_length]

        guess = random.choice(available)
        self.used_words.add(guess)
        return guess


class SmartBotStrategy(BotStrategy):
    """Intelligent strategy that learns from feedback"""

    def __init__(self, word_list: List[str]):
        self.word_list = word_list
        self.possible_words = set()
        self.eliminated_letters = set()
        self.confirmed_letters = {}
        self.wrong_positions: dict[str, set] = {}

    async def make_guess(
        self,
        word_length: int,
        previous_attempts: List[GuessResult],
        available_words: Optional[List[str]] = None,
    ) -> str:
        if not self.possible_words:
            self.possible_words = set(
                word for word in self.word_list if len(word) == word_length
            )

        for attempt in previous_attempts:
            self._update_knowledge(attempt)

        valid_words = self._filter_valid_words()

        if not valid_words:
            valid_words = list(self.possible_words) or [
                word for word in self.word_list if len(word) == word_length
            ]

        return random.choice(valid_words)

    def _update_knowledge(self, attempt_result: GuessResult):
        for i, letter_result in enumerate(attempt_result.letters):
            letter = letter_result.letter
            state = letter_result.state

            if state == LetterState.correct:
                self.confirmed_letters[i] = letter
            elif state == LetterState.misplaced:
                if letter not in self.wrong_positions:
                    self.wrong_positions[letter] = set()
                self.wrong_positions[letter].add(i)
            elif state == LetterState.absent:
                self.eliminated_letters.add(letter)

    def _filter_valid_words(self) -> List[str]:
        valid_words = []
        for word in self.possible_words:
            if self._is_word_valid(word):
                valid_words.append(word)
        return valid_words

    def _is_word_valid(self, word: str) -> bool:
        for pos, letter in self.confirmed_letters.items():
            if word[pos] != letter:
                return False

        for letter in self.eliminated_letters:
            if letter in word:
                return False

        for letter, wrong_positions in self.wrong_positions.items():
            if letter not in word:
                return False
            for pos in wrong_positions:
                if pos < len(word) and word[pos] == letter:
                    return False

        return True


class VirtualWebSocket(WebSocket):
    """Mock WebSocket for bot players that integrates with your existing system"""

    def __init__(self, bot_id: str):
        self.bot_id = bot_id
        self.is_connected = True
        self.message_queue = asyncio.Queue()
        self.client_state = WebSocketState.CONNECTED

    async def accept(self):
        """Mock accept method"""
        pass

    async def send_text(self, data: str):
        """Mock send - bots don't need to receive messages but this maintains interface"""
        pass

    async def send_json(self, data: dict):
        """Mock send_json - maintains WebSocket interface"""
        pass

    async def receive_text(self):
        """This will be called by your game loop - we'll provide bot moves here"""
        return await self.message_queue.get()

    async def close(self):
        self.is_connected = False


class BotPlayer:
    """Bot player that acts like a real player through VirtualWebSocket"""

    def __init__(
        self,
        bot_id: str,
        username: str,
        secret_word: str,
        strategy: BotStrategy,
        difficulty: str = "medium",
        response_delay_range: tuple = (2, 5),
    ):
        self.bot_id = bot_id
        self.username = username
        self.strategy = strategy
        self.difficulty = difficulty
        self.response_delay_range = response_delay_range
        self.virtual_ws = VirtualWebSocket(bot_id)
        self.secret_word: str = secret_word
        self.game_session_id: Optional[str] = None
        self._move_task: Optional[asyncio.Task] = None

    @property
    def user(self) -> WordleUser:
        """Create WordleUser representation"""
        return WordleUser(
            device_id=self.bot_id,
            username=self.username,
            user_id=self.bot_id,
            # Don't expose that it's a bot to maintain transparency
        )

    def set_game_context(self, game_session_id: str, secret_word: str):
        """Set game context for the bot"""
        self.game_session_id = game_session_id
        self.secret_word = secret_word

    async def start_playing(self, game_manager, word_length: int):
        """Start the bot's game loop - this runs independently"""
        # self._move_task = asyncio.create_task(
        #     self.play(game_manager, word_length)
        # )
        pass

    async def stop_playing(self):
        """Stop the bot's game loop"""
        if self._move_task and not self._move_task.done():
            self._move_task.cancel()
            try:
                await self._move_task
            except asyncio.CancelledError:
                pass

    async def play(self, game_manager: GameManager) -> Optional[str]:
        """
        Return the bot's next guess if it's the bot's turn.
        Otherwise, return None.
        """
        try:
            game_session = await game_manager.get_game_session(self.game_session_id)

            if not game_session or game_session.game_state != GameState.in_progress:
                return None

            bot_player_info = game_session.players.get(self.bot_id)
            if not bot_player_info:
                return None

            if game_session.current_turn != bot_player_info.role:
                return None  # Not bot's turn

            # Add realistic delay
            delay = random.uniform(*self.response_delay_range)
            await asyncio.sleep(delay)
            word_length = game_session.settings.word_length
            # Generate guess
            previous_attempts = [attempt.result for attempt in bot_player_info.attempts]
            guess = await self.strategy.make_guess(word_length, previous_attempts)
            print(f"Bot {self.bot_id} guessed: {guess}")
            # await self.virtual_ws.message_queue.put(guess)

            return guess

        except Exception as e:
            import traceback

            traceback.print_exc()
            logger.error(f"Bot play error: {e}")
            return None
