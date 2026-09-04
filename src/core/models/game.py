from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from sqlmodel import Field, SQLModel, Column
from sqlalchemy import JSON

from src.core.utils.time import get_current_time
from src.core.utils.uuid import generate_uuid


class Player(str, Enum):
    """Enumeration representing player roles or turns."""
    p1 = "player_1"
    p2 = "player_2"


class GameStatus(str, Enum):
    """Enumeration representing the current lifecycle status of a game."""
    WAITING = "waiting"
    IN_PROGRESS = "in_progress"
    PAUSED = "paused"
    GAME_OVER = "game_over"
    CANCELLED = "cancelled"


class Game(SQLModel, table=True):
    """
    Database model representing the complete persistent state of an ongoing or completed game.
    """
    # pyrefly: ignore [bad-override]
    __tablename__: Any = "games"

    # Core Identifiers and Game Status
    id: str = Field(
        default_factory=generate_uuid,
        primary_key=True,
        description="Unique identifier for the game session",
    )
    room_code: str = Field(
        index=True,
        unique=True,
        max_length=20,
        description="Code associated with the game room or lobby",
    )
    status: GameStatus = Field(
        default=GameStatus.IN_PROGRESS,
        index=True,
        description="Current lifecycle status of the game (waiting, in_progress, paused, game_over)",
    )
    current_turn: Optional[Player] = Field(
        default=Player.p1,
        description="Player whose turn it currently is (Player.p1 or Player.p2)",
    )


    # Player References (Foreign Keys to users.id)
    player_1: str = Field(
        foreign_key="users.id",
        index=True,
        description="Foreign key referencing player 1 in the users table",
    )
    player_2: Optional[str] = Field(
        default=None,
        foreign_key="users.id",
        index=True,
        nullable=True,
        description="Foreign key referencing player 2 in the users table (optional for solo/AI modes)",
    )

    # Secret Words assigned per round for each player
    player_1_words: Optional[List[str]] = Field(
        default_factory=list,
        sa_column=Column(JSON),
        description="List of secret words assigned to player 1 across all rounds",
    )
    player_2_words: Optional[List[str]] = Field(
        default_factory=list,
        sa_column=Column(JSON),
        description="List of secret words assigned to player 2 across all rounds",
    )

    # Configuration Data
    total_rounds: int = Field(
        default=1,
        description="Total number of rounds scheduled for this game match",
    )
    max_attempts: int = Field(
        default=6,
        description="Maximum allowed guess attempts per player for each word/round",
    )
    word_length: int = Field(
        default=4,
        description="Length of target secret words for the game",
    )

    # Current Game Progress and Statistics
    current_round: int = Field(
        default=1,
        description="Current round number being played",
    )
    player_1_score: int = Field(
        default=0,
        description="Total score accumulated by player 1",
    )
    player_2_score: int = Field(
        default=0,
        description="Total score accumulated by player 2",
    )
    player_1_attempts: Optional[List[Dict[str, Any]]] = Field(
        default_factory=list,
        sa_column=Column(JSON),
        description="Evaluated guess attempts for player 1 in the current turn",
    )
    player_2_attempts: Optional[List[Dict[str, Any]]] = Field(
        default_factory=list,
        sa_column=Column(JSON),
        description="Evaluated guess attempts for player 2 in the current turn",
    )

    # Power-up Usage State Tracking for Player 1 and Player 2
    player_1_fish_outs: Optional[List[str]] = Field(
        default_factory=list,
        sa_column=Column(JSON),
        description="State/history of fish out power-ups used by player 1",
    )
    player_2_fish_outs: Optional[List[str]] = Field(
        default_factory=list,
        sa_column=Column(JSON),
        description="State/history of fish out power-ups used by player 2",
    )
    player_1_reveal_letters: Optional[List[str]] = Field(
        default_factory=list,
        sa_column=Column(JSON),
        description="State/history of reveal letter power-ups used by player 1",
    )
    player_2_reveal_letters: Optional[List[str]] = Field(
        default_factory=list,
        sa_column=Column(JSON),
        description="State/history of reveal letter power-ups used by player 2",
    )
    player_1_meanings: Optional[Dict[str, str]] = Field(
        default_factory=dict,
        sa_column=Column(JSON),
        description="State/history of word meaning power-ups used by player 1",
    )
    player_2_meanings: Optional[Dict[str, str]] = Field(
        default_factory=dict,
        sa_column=Column(JSON),
        description="State/history of word meaning power-ups used by player 2",
    )


    # Game Outcome and Timestamps
    winner_id: Optional[str] = Field(
        default=None,
        foreign_key="users.id",
        index=True,
        nullable=True,
        description="Foreign key referencing the user who won the match",
    )
    created_at: Optional[datetime] = Field(
        default_factory=get_current_time,
        description="Timestamp when the game record was created",
    )
    updated_at: Optional[datetime] = Field(
        default_factory=get_current_time,
        description="Timestamp when the game record was last updated",
    )
    completed_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp when the game was completed",
    )



