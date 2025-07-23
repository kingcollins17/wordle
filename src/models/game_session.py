# src/models/game_session.py

from abc import ABC, abstractmethod
from pydantic import BaseModel, Field
from typing import Any, Callable, Coroutine, List, Dict, Optional, Literal
from enum import Enum
from uuid import UUID
from datetime import datetime, timedelta

from src.game.game_algorithm import (
    GuessResult,
    LetterResult,
    LetterState,
    GameAlgorithm,
)


class PowerUpType(str, Enum):
    FISH_OUT = "fish_out"
    AI_MEANING = "ai_meaning"
    REVEAL_LETTER = "reveal_letter"


class PowerUp(BaseModel):
    type: PowerUpType
    remaining: int = Field(..., description="Number of uses left for this power-up")


class RevealedLetter(BaseModel):
    letter: str = Field(..., description="The letter revealed from the opponent's word")
    index: int = Field(..., description="The position of the revealed letter")


class PowerUpResult(BaseModel):
    type: PowerUpType
    fished_letter: Optional[str] = Field(
        None, description="Letter not in the opponent's word (fish_out)"
    )
    revealed_letter: Optional[RevealedLetter] = Field(
        None,
        description="Letter and its index revealed from the opponent's word (reveal_letter)",
    )
    ai_meaning: Optional[str] = Field(
        None, description="AI-generated meaning of the word (ai_meaning)"
    )


class GameState(str, Enum):
    waiting = "waiting"
    in_progress = "in_progress"
    game_over = "game_over"


class PlayerRole(str, Enum):
    player1 = "player1"
    player2 = "player2"


# player_id means device_id and vice versa
class GuessAttempt(BaseModel):
    player_id: str
    result: Optional[GuessResult] = None
    guess: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class PlayerInfo(BaseModel):
    player_id: str
    username: Optional[str] = None
    role: PlayerRole
    secret_words: List[str] = Field(..., min_items=1)

    attempts: List[GuessAttempt] = Field(...)
    power_ups: List[PowerUp] = Field(default_factory=list)
    score: int = 0
    connected: bool = True

    class Config:
        use_enum_values = True


class GameSettings(BaseModel):

    rounds: int = 1  # Number of rounds per match
    max_attempts: int = 6
    word_length: int = 4
    round_time_limit: int = 60  # seconds per round
    language: str = "en"
    allow_powerups: bool = True
    versusAi: bool = False


class GameOutcome(BaseModel):
    winner_id: Optional[str] = None
    reason: Optional[str] = (
        None  # e.g., "opponent disconnected", "max attempts", "time out"
    )
    completed_at: datetime = Field(default_factory=datetime.utcnow)


class GameSession(BaseModel):
    session_id: str = Field(
        ..., description="A UUID4 string that uniquely identifies the game session"
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)
    players: Dict[str, PlayerInfo]  # keyed by user_id
    current_turn: PlayerRole  # user_id
    current_round: int = Field(default=1)
    game_state: GameState = Field(default=GameState.waiting)
    settings: GameSettings
    turn_timer_expires_at: Optional[datetime] = None
    outcome: Optional[GameOutcome] = None

    class Config:
        use_enum_values = True

    def is_last_round(self) -> bool:
        """Is this is the last round"""
        return self.current_round == self.settings.rounds

    def next_round(self) -> bool:
        if self.current_round < self.settings.rounds:
            self.current_round += 1
            return True
        return False

    def next_turn(self):
        """Switch to the next player's turn and optionally reset turn timer"""
        self.current_turn = (
            PlayerRole.player2
            if self.current_turn == PlayerRole.player1
            else PlayerRole.player1
        )

        if self.settings.round_time_limit:
            self.turn_timer_expires_at = datetime.utcnow() + timedelta(
                seconds=self.settings.round_time_limit
            )


class AfterGameHandler(ABC):
    async def __call__(self, game: GameSession) -> Any:
        return await self.handle(game)

    @abstractmethod
    async def handle(self, game: GameSession) -> Any:
        """
        Handle the game session after it has ended.

        Args:
            game: The GameSession object that has ended.

        Returns:
            Any: Result of the handling operation.
        """
        pass
