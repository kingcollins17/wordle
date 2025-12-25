# src/models/game_session.py

from abc import ABC, abstractmethod
from pydantic import BaseModel, Field
from typing import Any, Callable, Coroutine, List, Dict, Optional, Literal, Set
from enum import Enum
from uuid import UUID
from datetime import datetime, timedelta

from src.core.ai_service import WordDefinitionResponse
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
    ai_meaning: Optional[WordDefinitionResponse] = Field(
        None, description="AI-generated meaning of the word (ai_meaning)"
    )


class GameState(str, Enum):
    waiting = "waiting"
    in_progress = "in_progress"
    paused = "paused"
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
    avatar: Optional[str] = None
    role: PlayerRole
    secret_words: List[str] = Field(..., min_items=1)
    xp: Optional[int] = 0
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
    round_time_limit: int = 120  # seconds per round
    turn_time_limit: int = 5
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
    resume_votes: Set[str] = Field(default_factory=set)  # Set of player_ids who voted to resume

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

        self.turn_timer_expires_at = datetime.now() + timedelta(
            seconds=self.settings.turn_time_limit
        )

    def get_player_by_role(self, role: PlayerRole) -> Optional[PlayerInfo]:
        """Get player info by their role (player1 or player2)"""
        for player in self.players.values():
            if player.role == role:
                return player
        return None

    def get_opponent(self, player_id: str) -> Optional[PlayerInfo]:
        """Get the opponent's PlayerInfo for a given player_id"""
        current_player = self.players.get(player_id)
        if not current_player:
            return None

        opponent_role = (
            PlayerRole.player2
            if current_player.role == PlayerRole.player1
            else PlayerRole.player1
        )
        return self.get_player_by_role(opponent_role)

    def get_current_word(self, player_id: str) -> Optional[str]:
        """Get the current round's secret word for a player"""
        player = self.players.get(player_id)
        if not player or not player.secret_words:
            return None
        # Assuming each round uses the corresponding word in the list
        # If there are more rounds than words, use the last word
        word_index = min(self.current_round - 1, len(player.secret_words) - 1)
        return player.secret_words[word_index]

    def is_player_turn(self, player_id: str) -> bool:
        """Check if it's currently the given player's turn"""
        player = self.players.get(player_id)
        if not player:
            return False
        return player.role == self.current_turn

    def get_player_attempts(self, player_id: str) -> List[GuessAttempt]:
        """Get all guess attempts for a player"""
        player = self.players.get(player_id)
        return player.attempts if player else []

    def get_current_player(self) -> Optional[PlayerInfo]:
        """Get the PlayerInfo of the player whose turn it is currently"""
        return self.get_player_by_role(self.current_turn)

    def get_player_by_id(self, player_id: str) -> Optional[PlayerInfo]:
        """Get PlayerInfo by player_id"""
        return self.players.get(player_id)

    def both_players_connected(self) -> bool:
        """Check if both players are currently connected"""
        return all(player.connected for player in self.players.values())

    def request_resume(self, player_id: str) -> bool:
        """
        Request to resume the game. Returns True if all players have voted to resume.
        When all players vote, the game state is changed to in_progress and votes are cleared.
        """
        if player_id not in self.players:
            return False
        
        # Add player's vote
        self.resume_votes.add(player_id)
        
        # Check if all players have voted
        all_player_ids = set(self.players.keys())
        if self.resume_votes == all_player_ids:
            # All players ready, resume the game
            self.game_state = GameState.in_progress
            self.resume_votes.clear()
            return True
        
        return False

    def clear_resume_votes(self):
        """Clear all resume votes"""
        self.resume_votes.clear()


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
