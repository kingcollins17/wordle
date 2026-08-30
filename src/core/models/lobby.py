from datetime import datetime
from typing import Optional, List
from sqlmodel import Field, SQLModel

from src.core.utils.time import get_current_time
from src.core.utils.uuid import generate_uuid


class Lobby(SQLModel, table=True):
    # pyrefly: ignore [bad-override]
    __tablename__ = "lobbies"

    id: Optional[str] = Field(default_factory=generate_uuid, primary_key=True)
    code: str = Field(index=True, max_length=4)
    session_id: Optional[str] = Field(default=None, index=True, max_length=255)
    p1_id: Optional[str] = Field(default=None, index=True)
    p2_id: Optional[str] = Field(default=None, index=True)
    p1_words: Optional[str] = Field(default=None, max_length=2048)
    p2_words: Optional[str] = Field(default=None, max_length=2048)
    turn_time_limit: int = Field(default=120)
    word_length: int = Field(default=5)
    rounds: int = Field(default=5)
    created_at: Optional[datetime] = Field(default_factory=get_current_time)
    updated_at: Optional[datetime] = Field(default_factory=get_current_time)

    def get_p1_words_list(self) -> List[str]:
        if not self.p1_words:
            return []
        return [w.strip() for w in self.p1_words.rstrip(',').split(',') if w.strip()]

    def get_p2_words_list(self) -> List[str]:
        if not self.p2_words:
            return []
        return [w.strip() for w in self.p2_words.rstrip(',').split(',') if w.strip()]

    def is_ready(self) -> bool:
        return (
            self.p1_id is not None
            and self.p2_id is not None
            and self.p1_words is not None
            and self.p2_words is not None
        )
