from datetime import datetime
import json
from typing import List, Optional
from pydantic import BaseModel, Field, validator


class ChallengeBase(BaseModel):
    p1_id: int = Field(..., description="ID of player 1")
    p2_id: int = Field(..., description="ID of player 2")
    p1_username: str = Field(..., description="Username of player 1")
    p2_username: str = Field(..., description="Username of player 2")
    p1_secret_words: Optional[List[str]] = Field(
        ..., description="List of secret words for player 1"
    )
    p2_secret_words: Optional[List[str]] = Field(
        default=None, description="List of secret words for player 2"
    )
    lobby_code: str = Field(
        default=None, min_length=4, max_length=4, description="4-digit lobby code"
    )
    word_length: int = 5
    turn_time_limit: int = 120

    # validators to handle string -> list conversion
    @validator("p1_secret_words", "p2_secret_words", pre=True)
    def ensure_list(cls, v):
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                raise ValueError("Invalid JSON string for secret words")
        return v


class ChallengeCreate(ChallengeBase):
    """Used when creating a new challenge"""

    pass


class ChallengeUpdate(BaseModel):
    """Fields that can be updated in a challenge"""

    p1_secret_words: List[str] | None = None
    p2_secret_words: List[str] | None = None


class Challenge(ChallengeBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
