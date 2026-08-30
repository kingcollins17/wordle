from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel

from src.core.utils.time import get_current_time
from src.core.utils.uuid import generate_uuid


class Word(SQLModel, table=True):
    # pyrefly: ignore [bad-override]
    __tablename__ = "words"

    id: Optional[str] = Field(default_factory=generate_uuid, primary_key=True)
    random_id: Optional[int] = Field(default=None, index=True, unique=True)
    word: str = Field(index=True, max_length=255)
    meaning: Optional[str] = Field(default=None)
    word_length: int = Field(index=True)
    is_active: bool = Field(default=True)
    created_at: Optional[datetime] = Field(default_factory=get_current_time)
    updated_at: Optional[datetime] = Field(default_factory=get_current_time)
