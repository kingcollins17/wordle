from pyexpat.errors import messages
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from typing import Optional
import time
from firebase_admin import messaging
from src.database.mysql_connection_manager import get_mysql_manager
from src.database.redis_service import get_redis
from src.fcm_service import FCMService, get_fcm_service
from src.models import WordleUser
from ..repositories.user_repository import (
    UserRepository,
    get_current_user,
    get_user_repository,
)
from src.core import BaseResponse, APITags

auth_router = APIRouter(prefix="/users", tags=[APITags.USERS])


# Request body schema for user creation
class CreateUserRequest(BaseModel):
    device_id: str = Field(..., max_length=255)
    username: Optional[str] = Field(None, max_length=255)


@auth_router.post("/", response_model=BaseResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    request: CreateUserRequest, db=Depends(get_mysql_manager), redis=Depends(get_redis)
):
    repo = UserRepository(db, redis)

    # Check for existing device_id
    existing = await repo.get_user_by_device_id(request.device_id)
    if existing:
        raise HTTPException(
            status_code=400, detail="User with this device_id already exists"
        )

    # Check for existing username if provided
    if request.username:
        existing_username = await repo.get_user_by_username(request.username)
        if existing_username:
            raise HTTPException(status_code=400, detail="Username already taken")

    # Prepare user data for insertion
    user_data = {
        "device_id": request.device_id,
        "username": request.username or f"user_{request.device_id[:6]}",
        "xp": 0,
        "coins": 500,
        "games_played": 0,
    }

    await repo.create_user(user_data)

    return BaseResponse(
        success=True,
        message="User created successfully",
        data={"device_id": request.device_id},
    )


@auth_router.get("/by-device/{device_id}", response_model=BaseResponse)
async def get_user_by_device_id(
    device_id: str, db=Depends(get_mysql_manager), redis=Depends(get_redis)
):
    start_time = time.monotonic()

    repo = UserRepository(db, redis)
    user = await repo.get_user_by_device_id(device_id)

    elapsed = time.monotonic() - start_time

    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user = WordleUser(**user)
    return BaseResponse(
        success=True,
        message="User fetched successfully",
        data={"user": user, "query_time_seconds": round(elapsed, 6)},
    )


@auth_router.get("/update-reg-token", response_model=BaseResponse[dict])
async def update_device_reg_token(
    device_reg_token: str,
    db=Depends(get_mysql_manager),
    redis=Depends(get_redis),
    user: WordleUser = Depends(get_current_user),
    fcm: FCMService = Depends(get_fcm_service),
):
    try:
        if not device_reg_token:
            raise HTTPException(status_code=400, detail="device_reg_token is required")

        repo = UserRepository(db, redis)

        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        await repo.update_user_by_device_id(
            user.device_id, {"device_reg_token": device_reg_token}
        )
        try:
            pass
            # fcm.send_to_token(
            #     device_reg_token,
            #     notification=messaging.Notification(
            #         title="Test Notification", body="This is a test notification."
            #     ),
            # )  # Test
        except Exception as e:
            raise HTTPException(
                status_code=400, detail=f"Invalid device registration token: {e}"
            )
        return BaseResponse(
            success=True,
            message="Device registration token updated successfully",
            data={"device_id": user.device_id, "device_reg_token": device_reg_token},
        )

    except HTTPException:
        # Re-raise HTTPExceptions (FastAPI will handle them properly)
        raise
    except Exception as e:
        # Catch-all for unexpected errors
        raise HTTPException(status_code=500, detail=str(e))


@auth_router.get("/list-users", response_model=BaseResponse[list[WordleUser]])
async def list_users(
    q: Optional[str] = None,
    page: int = 1,
    per_page: int = 50,
    # db=Depends(get_mysql_manager),
    # redis=Depends(get_redis),
    repo: UserRepository = Depends(get_user_repository),
):
    """
    Search for users by username using MySQL REGEXP.
    """
    limit = per_page
    offset = (page - 1) * per_page
    start_time = time.monotonic()
    users: list[WordleUser] = []
    if q:
        res = await repo.search_users_by_username(q, limit, offset)
        if res:
            users = [WordleUser(**i) for i in res]
    else:
        users = await repo.list_users()

    elapsed = time.monotonic() - start_time

    if not users:
        raise HTTPException(status_code=404, detail="No users matched the pattern")

    return BaseResponse(
        success=True,
        message="Users fetched successfully",
        data=users,
    )
