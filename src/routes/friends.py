from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, Query
from typing import List, Literal, Optional
from aiomysql import IntegrityError
from src.fcm_service import FCMService, get_fcm_service
from firebase_admin import messaging
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
from src.repositories.user_repository import (
    UserRepository,
    get_current_user,
    get_user_repository,
)


friends_router = APIRouter(prefix="/friends", tags=[APITags.FRIENDS])


# ----------------------
# Friends
# ----------------------


@friends_router.get("", response_model=BaseResponse[List[FriendWithDetails]])
async def list_friends(
    user: WordleUser = Depends(get_current_user),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    repo: FriendsRepository = Depends(get_friends_repository),
):
    user_id = user.id
    limit = per_page
    offset = (page - 1) * per_page
    print(user)
    friends = await repo.list_friends_with_details(user_id, limit, offset)
    return BaseResponse(message="Friends list", data=friends)


@friends_router.delete("/remove/{friend_id}", response_model=BaseResponse[dict])
async def remove_friend(
    user: WordleUser = Depends(get_current_user),
    friend_id: int = Path(..., description="Friend ID to remove"),
    repo: FriendsRepository = Depends(get_friends_repository),
):

    user_id = user.id
    removed = await repo.remove_mutual_friendship(user_id, friend_id)
    return BaseResponse(message="Friend removed", data=removed)


@friends_router.get("/search", response_model=BaseResponse[List[FriendWithDetails]])
async def search_friends(
    user: WordleUser = Depends(get_current_user),
    q: str = Query(..., description="Search term"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    repo: FriendsRepository = Depends(get_friends_repository),
):
    user_id = user.id
    limit = per_page
    offset = (page - 1) * per_page
    results = await repo.search_friends(user_id, q, limit, offset)
    return BaseResponse(message="Friends search results", data=results)


@friends_router.get(
    "/mutual/{other_user_id}", response_model=BaseResponse[List[WordleUser]]
)
async def mutual_friends(
    user: WordleUser = Depends(get_current_user),
    other_user_id: int = Path(..., description="Other user ID"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    repo: FriendsRepository = Depends(get_friends_repository),
):
    user_id = user.id
    limit = per_page
    offset = (page - 1) * per_page
    mutuals = await repo.get_mutual_friends(user_id, other_user_id, limit, offset)
    return BaseResponse(message="Mutual friends", data=mutuals)


# ----------------------
# Friend Requests
# ----------------------


@friends_router.post("/requests", response_model=BaseResponse[FriendRequest])
async def send_friend_request(
    request: FriendRequestCreate,
    bg: BackgroundTasks,
    user_repo: UserRepository = Depends(get_user_repository),
    repo: FriendsRepository = Depends(get_friends_repository),
    user: WordleUser = Depends(get_current_user),
    fcm: FCMService = Depends(get_fcm_service),
):
    try:
        friend = await user_repo.get_user_by_id(request.receiver_id)
        if not friend:
            raise HTTPException(status_code=404, detail="User not found")
        friend = WordleUser(**friend)
        assert user.id == request.sender_id, "Sender ID must match current user ID"

        created_request = await repo.create_friend_request(request)

        if friend.device_reg_token:

            bg.add_task(
                fcm.send_to_token,
                token=friend.device_reg_token,
                data={"type": "friend_request", "app_url": "/friends"},
                notification=messaging.Notification(
                    title="Friend Request",
                    body=f"{user.username} wants to be your friend",
                ),
            )

        return BaseResponse(
            message=f"Friend request sent to {friend.username}", data=created_request
        )
    except IntegrityError:
        raise HTTPException(
            status_code=400,
            detail=f"You may have sent a friend request to {friend.username} previously",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error sending friend request: {e}"
        )


@friends_router.get(
    "/requests/received", response_model=BaseResponse[List[FriendRequestWithSender]]
)
async def list_received_requests(
    user: WordleUser = Depends(get_current_user),
    status: Optional[Literal["pending", "accepted", "declined"]] = Query(
        "pending", description="Filter by request status"
    ),
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
    status: Optional[Literal["pending", "accepted", "declined"]] = Query(
        "pending", description="Filter by request status"
    ),
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
    user_repo: UserRepository = Depends(get_user_repository),
    repo: FriendsRepository = Depends(get_friends_repository),
    user: WordleUser = Depends(get_current_user),
    fcm: FCMService = Depends(get_fcm_service),
):
    try:
        request = await repo.get_friend_request_by_id(request_id)
        if not request:
            raise HTTPException(status_code=404, detail="Friend request not found")

        sender = await user_repo.get_user_by_id(request.sender_id)
        if not sender:
            raise HTTPException(status_code=404, detail="Sender user not found")
        sender = WordleUser(**sender)

        # Authorization check
        assert user.id in (
            request.sender_id,
            request.receiver_id,
        ), "You are not authorized"

        if request.receiver_id != user.id:
            raise HTTPException(
                status_code=403, detail="Not authorized to update this request"
            )

        updated = await repo.update_friend_request_status(request_id, update)

        # Handle accepted
        if update.status == "accepted" and sender.device_reg_token:
            fcm.send_to_token(
                token=sender.device_reg_token,
                data={
                    "type": "friend_request_accepted",
                    "receiver_id": str(user.id),
                    "app_url": "/friends",
                },
                notification=messaging.Notification(
                    title="Friend Request Accepted",
                    body=f"{user.username} accepted your friend request",
                ),
            )

        # Handle declined
        if update.status == "declined":
            if sender.device_reg_token:
                fcm.send_to_token(
                    token=sender.device_reg_token,
                    data={
                        "type": "friend_request_declined",
                        "receiver_id": str(user.id),
                    },
                    notification=messaging.Notification(
                        title="Friend Request Declined",
                        body=f"{user.username} declined your friend request",
                    ),
                )
            # Delete the declined request
            await repo.delete_friend_request(request_id)
            return BaseResponse(message="Request declined and deleted", data=None)

        return BaseResponse(message=f"Request {update.status}", data=updated)

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error updating friend request: {e}"
        )
