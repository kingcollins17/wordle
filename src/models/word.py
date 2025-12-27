from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class Word(BaseModel):
    id: Optional[int] = Field(None, description="Auto-incrementing word ID")
    word: str = Field(..., max_length=255, description="The word itself")
    meaning: Optional[str] = Field(None, description="Meaning or definition of the word")
    word_length: int = Field(..., gt=0, description="Length of the word")
    is_active: bool = Field(False, description="Whether the word is active")
    created_at: Optional[datetime] = Field(None, description="Time of creation")
    updated_at: Optional[datetime] = Field(None, description="Time of last update")

    class Config:
        orm_mode = True
        ser_json_timedelta = "iso8601"
        ser_json_bytes = "utf8"
        ser_json_datetime = "iso8601"
