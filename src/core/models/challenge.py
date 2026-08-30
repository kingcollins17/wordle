from datetime import datetime
from typing import Optional, List
from sqlmodel import Field, SQLModel, Column
from sqlalchemy import JSON

from src.core.utils.time import get_current_time
from src.core.utils.uuid import generate_uuid


class Challenge(SQLModel, table=True):
    # pyrefly: ignore [bad-override]
    __tablename__ = "challenges"

    id: Optional[str] = Field(default_factory=generate_uuid, primary_key=True)
    p1_id: str = Field(index=True)
    p2_id: str = Field(index=True)
    p1_username: str = Field(max_length=255)
    p2_username: str = Field(max_length=255)
    p1_avatar: Optional[str] = Field(default=None)
    p2_avatar: Optional[str] = Field(default=None)
    p1_secret_words: Optional[List[str]] = Field(default=None, sa_column=Column(JSON))
    p2_secret_words: Optional[List[str]] = Field(default=None, sa_column=Column(JSON))
    lobby_code: Optional[str] = Field(default=None, max_length=4)
    word_length: int = Field(default=5)
    turn_time_limit: int = Field(default=120)
    created_at: Optional[datetime] = Field(default_factory=get_current_time)
    updated_at: Optional[datetime] = Field(default_factory=get_current_time)
