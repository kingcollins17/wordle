from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, Query
from typing import List, Optional
import logging

from src.fcm_service import FCMService, get_fcm_service
from src.core.models.friend import Friend, FriendRequest
from src.core.models.user import User
from src.core.repository import Repository, GetRepository
from src.core import BaseResponse, APITags, QueryOptions
from src.routes.auth import get_current_user

logger = logging.getLogger(__name__)

friends_router = APIRouter(prefix="/friends", tags=[APITags.FRIENDS])


@friends_router.get("", response_model=BaseResponse[List[Friend]])
async def list_friends(
    user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    repo: Repository[Friend] = Depends(GetRepository(Friend)),
):
    limit = per_page
    offset = (page - 1) * per_page
    options = QueryOptions(filters={"user_id": user.id}, limit=limit, offset=offset)
    friends = await repo.get_many(options=options)
    return BaseResponse(message="Friends list", data=friends)


@friends_router.delete("/remove/{friend_id}", response_model=BaseResponse[dict])
async def remove_friend(
    friend_id: str = Path(..., description="Friend ID to remove"),
    user: User = Depends(get_current_user),
    repo: Repository[Friend] = Depends(GetRepository(Friend)),
):
    options = QueryOptions(filters={"user_id": user.id, "friend_id": friend_id})
    existing = await repo.get(options=options)
    if existing:
        await repo.delete(existing)
    return BaseResponse(message="Friend removed", data={"removed": True})


@friends_router.get("/requests/received", response_model=BaseResponse[List[FriendRequest]])
async def list_received_requests(
    user: User = Depends(get_current_user),
    repo: Repository[FriendRequest] = Depends(GetRepository(FriendRequest)),
):
    options = QueryOptions(filters={"receiver_id": user.id, "status": "pending"})
    requests = await repo.get_many(options=options)
    return BaseResponse(message="Received requests list", data=requests)


@friends_router.post("/requests/send", response_model=BaseResponse[FriendRequest])
async def send_friend_request(
    receiver_id: str,
    user: User = Depends(get_current_user),
    req_repo: Repository[FriendRequest] = Depends(GetRepository(FriendRequest)),
    user_repo: Repository[User] = Depends(GetRepository(User)),
):
    receiver = await user_repo.get(id=receiver_id)
    if not receiver:
        raise HTTPException(status_code=404, detail="Receiver not found")

    freq = FriendRequest(sender_id=user.id, receiver_id=receiver_id, status="pending")
    created = await req_repo.add(freq)
    return BaseResponse(message="Friend request sent", data=created)
