from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel

from src.core.utils.time import get_current_time
from src.core.utils.uuid import generate_uuid


class FriendRequest(SQLModel, table=True):
    # pyrefly: ignore [bad-override]
    __tablename__ = "friend_requests"

    id: Optional[str] = Field(default_factory=generate_uuid, primary_key=True)
    sender_id: str = Field(index=True)
    receiver_id: str = Field(index=True)
    status: str = Field(default="pending", max_length=50)
    created_at: Optional[datetime] = Field(default_factory=get_current_time)
    updated_at: Optional[datetime] = Field(default_factory=get_current_time)


class Friend(SQLModel, table=True):
    # pyrefly: ignore [bad-override]
    __tablename__ = "friends"

    id: Optional[str] = Field(default_factory=generate_uuid, primary_key=True)
    user_id: str = Field(index=True)
    friend_id: str = Field(index=True)
    created_at: Optional[datetime] = Field(default_factory=get_current_time)
