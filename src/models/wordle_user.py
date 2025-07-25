from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime


# src/models/wordle_user.py
class WordleUser(BaseModel):
    id: Optional[int] = Field(None, description="Auto-incrementing user ID")
    device_id: str = Field(..., max_length=255, description="Unique device ID")
    username: str = Field(..., max_length=255, description="Unique username")
    email: Optional[EmailStr] = Field(None, description="Optional email address")
    xp: int = Field(0, ge=0, description="Experience points")
    coins: int = Field(500, ge=0, description="Starting coin balance")
    games_played: int = Field(0, ge=0, description="Total games played")
    reveal_letter: int = Field(
        1, ge=0, description="Number of uses for reveal letter power-up"
    )
    fish_out: int = Field(1, ge=0, description="Number of uses for fish out power-up")
    ai_meaning: int = Field(
        1, ge=0, description="Number of uses for AI meaning power-up"
    )
    created_at: Optional[datetime] = Field(None, description="Time of account creation")
    updated_at: Optional[datetime] = Field(None, description="Time of last update")

    class Config:
        orm_mode = True
        ser_json_timedelta = "iso8601"
        ser_json_bytes = "utf8"
        ser_json_datetime = "iso8601"
