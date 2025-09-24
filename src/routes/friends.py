from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from src.repositories.friends_repository import (
    FriendsRepository,
    get_friends_repository,
)
from src.models.friend_request import (
    FriendRequestCreate,
    FriendRequestUpdate,
    FriendRequest,
    FriendRequestWithSender,
    FriendRequestWithDetails,
)
from src.models.friends_model import Friend, FriendWithDetails
from src.models.wordle_user import WordleUser
from src.core import BaseResponse, APITags
from src.repositories.user_repository import get_current_user


friends_router = APIRouter(prefix="/friends", tags=[APITags.FRIENDS])


# ----------------------
# Friend Requests
# ----------------------


@friends_router.post("/requests", response_model=BaseResponse[FriendRequest])
async def send_friend_request(
    request: FriendRequestCreate,
    repo: FriendsRepository = Depends(get_friends_repository),
):
    created_request = await repo.create_friend_request(request)
    return BaseResponse(message="Friend request sent", data=created_request)


@friends_router.get(
    "/requests/received", response_model=BaseResponse[List[FriendRequestWithSender]]
)
async def list_received_requests(
    user: WordleUser = Depends(get_current_user),
    status: Optional[str] = Query(None, description="Filter by request status"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    repo: FriendsRepository = Depends(get_friends_repository),
):
    user_id = user.id
    limit = per_page
    offset = (page - 1) * per_page
    requests = await repo.list_friend_requests_received(user_id, status, limit, offset)
    return BaseResponse(message="Received friend requests", data=requests)


@friends_router.get(
    "/requests/sent", response_model=BaseResponse[List[FriendRequestWithSender]]
)
async def list_sent_requests(
    user: WordleUser = Depends(get_current_user),
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    repo: FriendsRepository = Depends(get_friends_repository),
):
    user_id = user.id
    limit = per_page
    offset = (page - 1) * per_page
    requests = await repo.list_friend_requests_sent(user_id, status, limit, offset)
    return BaseResponse(message="Sent friend requests", data=requests)


@friends_router.patch(
    "/requests/{request_id}", response_model=BaseResponse[FriendRequest]
)
async def update_request_status(
    request_id: int,
    update: FriendRequestUpdate,
    repo: FriendsRepository = Depends(get_friends_repository),
):
    updated = await repo.update_friend_request_status(request_id, update)
    if not updated:
        raise HTTPException(status_code=404, detail="Friend request not found")
    return BaseResponse(message=f"Request {update.status}", data=updated)


# ----------------------
# Friends
# ----------------------


@friends_router.get("/", response_model=BaseResponse[List[FriendWithDetails]])
async def list_friends(
    user: WordleUser = Depends(get_current_user),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    repo: FriendsRepository = Depends(get_friends_repository),
):
    user_id = user.id
    limit = per_page
    offset = (page - 1) * per_page
    friends = await repo.list_friends_with_details(user_id, limit, offset)
    return BaseResponse(message="Friends list", data=friends)


@friends_router.delete("/{friend_id}", response_model=BaseResponse[dict])
async def remove_friend(
    user: WordleUser = Depends(get_current_user),
    friend_id: int = Query(..., description="Friend ID to remove"),
    repo: FriendsRepository = Depends(get_friends_repository),
):
    user_id = user.id
    removed = await repo.remove_mutual_friendship(user_id, friend_id)
    return BaseResponse(message="Friend removed", data=removed)


@friends_router.get("/search", response_model=BaseResponse[List[FriendWithDetails]])
async def search_friends(
    user_id: int = Query(...),
    q: str = Query(..., description="Search term"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    repo: FriendsRepository = Depends(get_friends_repository),
):
    limit = per_page
    offset = (page - 1) * per_page
    results = await repo.search_friends(user_id, q, limit, offset)
    return BaseResponse(message="Friends search results", data=results)


@friends_router.get(
    "/mutual/{other_user_id}", response_model=BaseResponse[List[WordleUser]]
)
async def mutual_friends(
    user_id: int = Query(..., description="Current user ID"),
    other_user_id: int = Query(..., description="Other user ID"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    repo: FriendsRepository = Depends(get_friends_repository),
):
    limit = per_page
    offset = (page - 1) * per_page
    mutuals = await repo.get_mutual_friends(user_id, other_user_id, limit, offset)
    return BaseResponse(message="Mutual friends", data=mutuals)
