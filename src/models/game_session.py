# src/models/game_session.py

from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Literal
from enum import Enum
from uuid import UUID
from datetime import datetime, timedelta

from src.game.game_algorithm import (
    GuessResult,
    LetterResult,
    LetterState,
    GameAlgorithm,
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


_eg = {
    "session_id": "123e4567-e89b-12d3-a456-426614174000",
    "players": {
        "userA": {
            "user_id": "userA",
            "username": "Alice",
            "score": 2,
        },
        "userB": {
            "user_id": "userB",
            "username": "Bob",
            "score": 1,
        },
    },
    "current_turn": "userA",
    "game_state": "in_progress",
    "word_data": {
        "userA": {"target_word": "QUIZ", "masked_word": "_ _ _ _", "guesses": []},
        "userB": {"target_word": "GAME", "masked_word": "_ _ _ _", "guesses": []},
    },
}
