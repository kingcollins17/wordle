from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel

from src.core.utils.time import get_current_time
from src.core.utils.uuid import generate_uuid


class Reward(SQLModel, table=True):
    # pyrefly: ignore [bad-override]
    __tablename__ = "rewards"

    id: Optional[str] = Field(default_factory=generate_uuid, primary_key=True)
    user_id: str = Field(index=True, foreign_key="users.id")

    # Reward items
    coins: int = Field(default=0)
    fish_out: int = Field(default=0)
    reveal_letter: int = Field(default=0)
    word_meaning: int = Field(default=0)

    # Status
    is_read: bool = Field(default=False, index=True)

    # Metadata
    title: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = Field(default=None)

    # Timestamps
    created_at: Optional[datetime] = Field(default_factory=get_current_time)
    updated_at: Optional[datetime] = Field(default_factory=get_current_time)

    def __init__(self, **data):
        # Normalize plural variations for ease of use
        if "fish_outs" in data and "fish_out" not in data:
            data["fish_out"] = data.pop("fish_outs")
        if "reveal_letters" in data and "reveal_letter" not in data:
            data["reveal_letter"] = data.pop("reveal_letters")
        if "word_meanings" in data and "word_meaning" not in data:
            data["word_meaning"] = data.pop("word_meanings")
        super().__init__(**data)

    @property
    def fish_outs(self) -> int:
        return self.fish_out

    @property
    def reveal_letters(self) -> int:
        return self.reveal_letter

    @property
    def word_meanings(self) -> int:
        return self.word_meaning
