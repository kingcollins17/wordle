from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class DatabaseLobby(BaseModel):
    """Database model for lobby rooms"""
    
    id: Optional[int] = Field(None, description="Auto-incrementing lobby ID")
    code: str = Field(..., max_length=4, description="4-character lobby code")
    session_id: Optional[str] = Field(
        None,
        max_length=255,
        description="Game session ID when game is created from lobby"
    )
    p1_id: Optional[int] = Field(None, description="Player 1 user ID")
    p2_id: Optional[int] = Field(None, description="Player 2 user ID")
    p1_device_id: Optional[str] = Field(
        None, 
        max_length=255, 
        description="Player 1 device ID"
    )
    p2_device_id: Optional[str] = Field(
        None, 
        max_length=255, 
        description="Player 2 device ID"
    )
    p1_words: Optional[str] = Field(
        None, 
        max_length=2048, 
        description="Comma-separated list of Player 1's words"
    )
    p2_words: Optional[str] = Field(
        None, 
        max_length=2048, 
        description="Comma-separated list of Player 2's words"
    )
    turn_time_limit: int = Field(
        120, 
        ge=1, 
        description="Turn time limit in seconds"
    )
    word_length: int = Field(..., ge=1, description="Length of words in the game")
    rounds: int = Field(..., ge=1, description="Number of rounds to play")
    created_at: Optional[datetime] = Field(
        None, 
        description="Time the lobby was created"
    )
    updated_at: Optional[datetime] = Field(
        None, 
        description="Time the lobby was last updated"
    )

    class Config:
        orm_mode = True
        ser_json_timedelta = "iso8601"
        ser_json_bytes = "utf8"
        ser_json_datetime = "iso8601"

    def get_p1_words_list(self) -> List[str]:
        """Parse p1_words string into a list"""
        if not self.p1_words:
            return []
        return [w.strip() for w in self.p1_words.rstrip(',').split(',') if w.strip()]

    def get_p2_words_list(self) -> List[str]:
        """Parse p2_words string into a list"""
        if not self.p2_words:
            return []
        return [w.strip() for w in self.p2_words.rstrip(',').split(',') if w.strip()]

    def is_ready(self) -> bool:
        """Check if lobby is ready to start (both players have joined)"""
        return (
            self.p1_id is not None 
            and self.p2_id is not None 
            and self.p1_words is not None 
            and self.p2_words is not None
        )
