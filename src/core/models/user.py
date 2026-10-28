from datetime import datetime
import secrets
import string
from typing import Optional
from sqlmodel import Field, SQLModel

from src.core.utils.time import get_current_time
from src.core.utils.uuid import generate_uuid



def _generate_refcode() -> str:
    return ''.join(secrets.choice(string.digits) for _ in range(6))

class User(SQLModel, table=True):
    # pyrefly: ignore [bad-override]
    __tablename__ = "users"

    id: str = Field(default_factory=generate_uuid, primary_key=True)
    username: str = Field(index=True, unique=True, max_length=255)
    device_reg_token: Optional[str] = Field(default=None)
    avatar: Optional[str] = Field(default=None)
    xp: int = Field(default=10)
    coins: int = Field(default=500)
    games_played: int = Field(default=0)
    reveal_letter: int = Field(default=1)
    fish_out: int = Field(default=1)
    word_meaning: int = Field(default=1)

    referral_code: Optional[str] = Field(default_factory=_generate_refcode, unique=True)
    referrer_id: Optional[str] = Field(default=None)
    created_at: Optional[datetime] = Field(default_factory=get_current_time)
    updated_at: Optional[datetime] = Field(default_factory=get_current_time)

WordleUser=User