from enum import Enum
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field

from src.game.game_algorithm import PowerUpType


class PowerUpUsageResult(BaseModel):
    """Result returned when a player uses a power-up."""
    powerup_type: PowerUpType
    fished_letter: Optional[str] = None
    revealed_letter: Optional[str] = None
    revealed_index: Optional[int] = None
    word_meaning: Optional[str] = None

    model_config = {"use_enum_values": True}


class GameEventType(str, Enum):
    """All event types the GameManager can broadcast to players."""
    GAME_STARTED = "game_started"
    GUESS_MADE = "guess_made"
    TURN_WON = "turn_won"
    TURN_LOST = "turn_lost"
    # ROUND_ENDED = "round_ended"
    GAME_OVER = "game_over"
    GAME_PAUSED = "game_paused"
    GAME_RESUMED = "game_resumed"
    POWERUP_USED = "powerup_used"
    ERROR = "error"


class GameEvent(BaseModel):
    """
    Envelope broadcast to both players over WebSocket after every game action.
    Carries the event type, a dict snapshot of the current Game state,
    and an optional event-specific payload.
    """
    event_type: GameEventType
    game_state: dict
    payload: Optional[Any] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    model_config = {"use_enum_values": True}
