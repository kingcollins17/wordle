from datetime import datetime
from pydantic import BaseModel, Field

from src.models.wordle_user import WordleUser


class FriendBase(BaseModel):
    user_id: int = Field(..., description="ID of the user")
    friend_id: int = Field(..., description="ID of the friend")


class FriendCreate(FriendBase):
    """Used when creating a new friendship"""

    pass


class Friend(FriendBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class FriendWithDetails(WordleUser):
    """Extended user model that includes friendship creation date"""

    friendship_created_at: datetime

    class Config:
        from_attributes = True
