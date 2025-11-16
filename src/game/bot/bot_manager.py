# bot/bot_manager.py
import random
from typing import Dict, List, Optional
import logging
from fastapi import Depends
from src.database import RedisService
from src.database.redis_service import get_redis
from .bot_player import *
from ..words import *

logger = logging.getLogger(__name__)


class BotManager:
    """Manages bot players independently of GameManager"""

    def __init__(
        self,
        redis_service: RedisService,
        threes: List[str],
        fours: List[str],
        fives: List[str],
        sixes: List[str],
    ):
        self.redis = redis_service
        self.fours = fours
        self.threes = threes
        self.fives = fives
        self.sixes = sixes
        self.active_bots: Dict[str, BotPlayer] = {}
        self.bot_names = [
            "WordWiz",
            "LetterLord",
            "GuessGuru",
            "VocabVictor",
            "WordSmith",
            "LetterLegend",
            "PuzzlePro",
            "WordWarden",
        ]

    def _get_words_list(self, length: int, n: int = 20):
        """
        Return a list of words of the given length.
        If n is provided, return n random words from that list.
        """
        assert length in [3, 4, 5, 6], f"Word length of {length} is not allowed"

        # Select the appropriate list
        words = {
            3: self.threes,
            4: self.fours,
            5: self.fives,
            6: self.sixes,
        }[length]

        # If n is not specified, or n >= length of list, return full list
        if n is None or n >= len(words):
            return words

        # Return n random unique items
        return random.sample(words, n)

    def create_bot(
        self,
        difficulty: str = "medium",
        word_length: int = 4,
        opponents_word: Optional[str] = None,
    ) -> BotPlayer:
        """Create a new bot with specified difficulty"""
        bot_id = f"bot_{random.randint(10000, 99999)}"
        word_list = self._get_words_list(word_length)

        # add opponents word so bot can guess it
        word_list.append(opponents_word)

        if difficulty == "easy":
            strategy = RandomBotStrategy(word_list)
            delay_range = (3, 7)
        elif difficulty == "hard":
            strategy = SmartBotStrategy(word_list)
            delay_range = (1, 3)
        else:  # medium
            strategy = SmartBotStrategy(word_list)
            delay_range = (2, 5)

        username = f"{random.choice(self.bot_names)}{random.randint(10, 99)}"

        bot = BotPlayer(
            bot_id=bot_id,
            username=username,
            strategy=strategy,
            difficulty=difficulty,
            response_delay_range=delay_range,
            secret_word=random.choice(word_list),
        )

        self.active_bots[bot_id] = bot
        if opponents_word and opponents_word.lower() not in word_list:
            word_list.append(opponents_word.lower())

        return bot

    def get_bot(self, bot_id: str) -> Optional[BotPlayer]:
        return self.active_bots.get(bot_id)

    def is_bot(self, player_id: str) -> bool:
        return player_id.startswith("bot_")

    async def reconnect_bot(
        self,
        bot_id: str,
        game_session_id: str,
        game_manager: GameManager,
        word_length: int,
        difficulty="medium",
    ):
        """Reconnect a bot to the game if it's not currently active."""

        bot = self.get_bot(bot_id)

        if not bot:
            # Bot is not active — reconstruct from game session
            game_session = await game_manager.get_game_session(game_session_id)
            if not game_session:
                logger.error(f"Cannot reconnect bot {bot_id}: game session not found")
                return

            player_info = game_session.players.get(bot_id)
            if not player_info:
                logger.error(
                    f"Cannot reconnect bot {bot_id}: player not found in session"
                )
                return

            # Load correct word list
            word_list = self._get_words_list(word_length)

            # Match difficulty logic used in create_bot()
            if difficulty == "easy":
                strategy = RandomBotStrategy(word_list)
                delay_range = (3, 7)
            elif difficulty == "hard":
                strategy = SmartBotStrategy(word_list)
                delay_range = (1, 3)
            else:  # medium
                strategy = SmartBotStrategy(word_list)
                delay_range = (2, 5)

            # Use stored username or fallback
            username = player_info.username or "Bot"

            # Secret word from player_info (correct field is plural in your snippet)
            secret_word = player_info.secret_words

            bot = BotPlayer(
                bot_id=bot_id,
                username=username,
                strategy=strategy,
                difficulty=difficulty,
                response_delay_range=delay_range,
                secret_word=secret_word,
            )
            self.active_bots[bot_id] = bot

        # Reassign context and restart bot logic
        bot.set_game_context(game_session_id, bot.secret_word)
        await bot.start_playing(game_manager, word_length)


_bot_manager: Optional[BotManager] = None


async def get_bot_manager(redis: RedisService = Depends(get_redis)) -> BotManager:
    global _bot_manager
    if _bot_manager is None:

        _bot_manager = BotManager(
            redis,
            threes=three_letter_words,
            fours=four_letter_words,
            fives=five_letter_words,
            sixes=six_letter_words,
        )
    return _bot_manager
