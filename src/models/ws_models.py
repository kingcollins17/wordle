from pydantic import BaseModel, Field, root_validator, model_validator
from typing import Any, Union, Literal, Optional, List, Dict
from enum import Enum
from .game_session import GameSession, PlayerInfo, PlayerRole, GuessAttempt


class PowerUpType(str, Enum):
    FISH_OUT = "fish_out"
    AI_MEANING = "ai_meaning"
    REVEAL_LETTER = "reveal_letter"


class MessageType(str, Enum):
    # Core game
    INIT = "init"
    WAITING = "waiting"
    RESULT = "result"  # send result when a round is complete, but if game is over, send game over
    GUESS = "guess"
    TURN = "turn"
    CONFIGURE = "configure"
    GAME_OVER = "game_over"
    GAME_STATE = "game_state"

    # Power-ups
    POWERUP = "powerup"
    POWERUP_RESULT = "powerup_result"

    # Matchmaking
    MATCHED = "matched"
    CANCEL_MATCHMAKING = "cancel_matchmaking"
    LEAVE_GAME = "leave_game"

    # System
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"
    INFO = "info"
    HEARTBEAT = "heartbeat"


# === 🎮 Game-Related Payloads === #


class GameStatePayload(GameSession): ...


class WaitingPayload(BaseModel):
    waiting_for: str


class ConfigurePayload(BaseModel):
    rounds: int = Field(default=1, description="Number of rounds per match")
    word_length: int = Field(default=4, description="Length of the secret word")


class GuessPayload(BaseModel):
    attempt_result: GuessAttempt
    current_turn: PlayerRole


class InitPayload(BaseModel):
    player_id: str
    game_id: Optional[str] = None  # Optional if reconnecting


class SetWordPayload(BaseModel):
    word: str = Field(..., min_length=3, max_length=10)


class TurnPayload(BaseModel):
    player_id: str


class ResultPayload(BaseModel):
    round_winner: str
    guess: str
    result: GuessAttempt


class GameOverPayload(BaseModel):
    winner_id: Optional[str] = Field(
        ..., description="If winner id is null, means there was no winner"
    )
    reason: str


# === ⚡ Power-up Payloads === #


class PowerUpPayload(BaseModel):
    powerup_type: PowerUpType

    model_config = {"use_enum_values": True}


class PowerUpResultPayload(BaseModel):
    powerup_type: PowerUpType
    result: Union[
        List[str],  # for fish_letters
        str,  # for ai_meaning
        Dict[str, Union[str, int]],  # for reveal_letter: {"index": 2, "letter": "e"}
    ]

    model_config = {"use_enum_values": True}


# === 🧑‍🤝‍🧑 Matchmaking Payloads === #


class MatchedPayload(BaseModel):
    game_id: str
    player_id: str
    opponent_id: str
    role: Literal["player1", "player2"]


# === ⚠️ System & Meta Messages === #


class ErrorPayload(BaseModel):
    message: str
    code: Optional[int] = None


class InfoPayload(BaseModel):
    message: str


class HeartbeatPayload(BaseModel):
    ts: float  # timestamp in seconds


# === 📦 Envelope Message Model === #


class WebSocketMessage(BaseModel):
    type: MessageType
    data: Union[
        InitPayload,
        SetWordPayload,
        GuessPayload,
        TurnPayload,
        ResultPayload,
        GameOverPayload,
        PowerUpPayload,
        PowerUpResultPayload,
        MatchedPayload,
        ErrorPayload,
        InfoPayload,
        HeartbeatPayload,
        GameStatePayload,
        Any,
    ]

    model_config = {"use_enum_values": True}

    # @model_validator(mode="after")
    # def validate_data_type(self):
    #     if self.type in (
    #         MessageType.CONNECTED,
    #         MessageType.DISCONNECTED,
    #         MessageType.GAME_OVER,
    #         MessageType.GAME_STATE,
    #     ):
    #         return self

    #     expected_type_map = {
    #         "init": InitPayload,
    #         "set_word": SetWordPayload,
    #         "guess": GuessPayload,
    #         "turn": TurnPayload,
    #         "result": ResultPayload,
    #         "game_over": GameOverPayload,
    #         "powerup": PowerUpPayload,
    #         "powerup_result": PowerUpResultPayload,
    #         "matched": MatchedPayload,
    #         "error": ErrorPayload,
    #         "info": InfoPayload,
    #         "heartbeat": HeartbeatPayload,
    #     }

    #     expected_type = expected_type_map.get(self.type)
    #     if expected_type and not isinstance(
    #         self.data, tuple(expected_type_map.values())
    #     ):
    #         raise ValueError(
    #             f"Expected {expected_type.__name__} for type '{self.type}', got {type(self.data).__name__}"
    #         )

    #     return self
