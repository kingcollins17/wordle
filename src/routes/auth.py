from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from typing import Optional
import time

from src.database.mysql_connection_manager import get_mysql_manager
from src.database.redis_service import get_redis
from src.models import WordleUser
from ..repositories.user_repository import UserRepository
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
