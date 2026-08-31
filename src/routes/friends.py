from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, Query
from typing import List, Optional, Dict
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
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    req_repo: Repository[FriendRequest] = Depends(GetRepository(FriendRequest)),
    user_repo: Repository[User] = Depends(GetRepository(User)),
    fcm_service: FCMService = Depends(get_fcm_service),
):
    if receiver_id == user.id:
        raise HTTPException(status_code=400, detail="Cannot send friend request to yourself")

    receiver = await user_repo.get(id=receiver_id)
    if not receiver:
        raise HTTPException(status_code=404, detail="Receiver not found")

    existing = await req_repo.get(
        options=QueryOptions(
            filters={"sender_id": user.id, "receiver_id": receiver_id}
        )
    )
    if existing:
        if existing.status == "pending":
            raise HTTPException(status_code=400, detail="Friend request already sent")
        elif existing.status == "accepted":
            raise HTTPException(status_code=400, detail="You are already friends")

    freq = FriendRequest(sender_id=user.id, receiver_id=receiver_id, status="pending")
    created = await req_repo.add(freq)

    # Notify receiver via FCM push notification using injected dependency
    if receiver.device_reg_token:
        notification = fcm_service.create_notification(
            title="New Friend Request",
            body=f"{user.username} sent you a friend request.",
        )
        data = {
            "type": "friend_request",
            "sender_id": user.id,
            "sender_username": user.username,
            "request_id": str(created.id),
        }
        background_tasks.add_task(
            fcm_service.send,
            token=receiver.device_reg_token,
            notification=notification,
            data=data,
        )

    return BaseResponse(message="Friend request sent", data=created)


@friends_router.post("/requests/accept/{request_id}", response_model=BaseResponse[dict])
async def accept_friend_request(
    request_id: str,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    req_repo: Repository[FriendRequest] = Depends(GetRepository(FriendRequest)),
    friend_repo: Repository[Friend] = Depends(GetRepository(Friend)),
    user_repo: Repository[User] = Depends(GetRepository(User)),
    fcm_service: FCMService = Depends(get_fcm_service),
):
    freq = await req_repo.get(id=request_id)
    if not freq:
        raise HTTPException(status_code=404, detail="Friend request not found")

    if freq.receiver_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to accept this request")

    if freq.status == "accepted":
        raise HTTPException(status_code=400, detail="Friend request already accepted")

    # Update status to accepted
    await req_repo.update(freq, {"status": "accepted"})

    # Create bidirectional Friend entries
    friend_entry1 = Friend(user_id=user.id, friend_id=freq.sender_id)
    friend_entry2 = Friend(user_id=freq.sender_id, friend_id=user.id)
    await friend_repo.add_many([friend_entry1, friend_entry2], refresh=False)

    # Fetch sender user and send FCM push notification using injected dependency
    sender = await user_repo.get(id=freq.sender_id)
    if sender and sender.device_reg_token:
        notification = fcm_service.create_notification(
            title="Friend Request Accepted",
            body=f"{user.username} accepted your friend request.",
        )
        data = {
            "type": "friend_request_accepted",
            "user_id": user.id,
            "username": user.username,
            "request_id": str(freq.id),
        }
        background_tasks.add_task(
            fcm_service.send,
            token=sender.device_reg_token,
            notification=notification,
            data=data,
        )

    return BaseResponse(message="Friend request accepted", data={"accepted": True})


@friends_router.post("/requests/decline/{request_id}", response_model=BaseResponse[dict])
async def decline_friend_request(
    request_id: str,
    user: User = Depends(get_current_user),
    req_repo: Repository[FriendRequest] = Depends(GetRepository(FriendRequest)),
):
    freq = await req_repo.get(id=request_id)
    if not freq:
        raise HTTPException(status_code=404, detail="Friend request not found")

    if freq.receiver_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to decline this request")

    await req_repo.update(freq, {"status": "declined"})
    return BaseResponse(message="Friend request declined", data={"declined": True})
