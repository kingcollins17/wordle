from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class Game(BaseModel):
    id: Optional[int] = Field(None, description="Auto-incrementing game ID")
    p1_id: int = Field(..., description="Player 1 user ID")
    p2_id: int = Field(..., description="Player 2 user ID")
    winner_id: Optional[int] = Field(
        None, description="Winner user ID (nullable if draw)"
    )
    p1_username: str = Field(..., max_length=255, description="Player 1 username")
    p2_username: str = Field(..., max_length=255, description="Player 2 username")
    p1_device_id: str = Field(..., max_length=255, description="Player 1 device ID")
    p2_device_id: str = Field(..., max_length=255, description="Player 2 device ID")

    p1_secret_words: List[str] = Field(
        default_factory=list, description="JSON list of Player 1's secret words"
    )
    p2_secret_words: List[str] = Field(
        default_factory=list, description="JSON list of Player 2's secret words"
    )
    created_at: Optional[datetime] = Field(
        None, description="Time the game was created"
    )
    rounds: int = Field(0, ge=0, description="Number of rounds played")
    completed_at: Optional[datetime] = Field(None, description="Time the game ended")

    class Config:
        orm_mode = True
        ser_json_timedelta = "iso8601"
        ser_json_bytes = "utf8"
        ser_json_datetime = "iso8601"
