from typing import Literal, Optional
from datetime import datetime
from pydantic import BaseModel, Field


class FriendRequestBase(BaseModel):
    sender_id: int = Field(..., description="ID of the user who sent the request")
    receiver_id: int = Field(..., description="ID of the user receiving the request")
    status: Literal["pending", "accepted", "declined"] = Field(
        default="pending", description="New status of the request"
    )


class FriendRequestCreate(FriendRequestBase):
    """Used when creating a new friend request"""

    pass


class FriendRequestUpdate(BaseModel):
    status: Literal["pending", "accepted", "declined"] = Field(
        default="pending", description="New status of the request"
    )


class FriendRequest(FriendRequestBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class FriendRequestWithSender(FriendRequest):
    """Friend request model with sender details"""

    sender_username: str
    sender_email: Optional[str] = None
    sender_xp: int
    sender_coins: int

    class Config:
        from_attributes = True


class FriendRequestWithDetails(FriendRequest):
    """Friend request model with both sender and receiver details"""

    sender_username: str
    sender_email: Optional[str] = None
    sender_xp: int
    sender_coins: int
    receiver_username: str
    receiver_email: Optional[str] = None
    receiver_xp: int
    receiver_coins: int

    class Config:
        from_attributes = True
