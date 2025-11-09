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
    avatar: Optional[str] = None


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
        "avatar": request.avatar,
        "coins": 500,
        "games_played": 0,
    }

    await repo.create_user(user_data)

    return BaseResponse(
        success=True,
        message="User created successfully",
        data={"device_id": request.device_id},
    )


class UpdateUserRequest(BaseModel):
    username: Optional[str] = Field(None, max_length=255)
    avatar: Optional[str] = Field(None)


@auth_router.put("/update-profile", response_model=BaseResponse)
async def update_user_profile(
    request: UpdateUserRequest,
    user: WordleUser = Depends(get_current_user),
    repo: UserRepository = Depends(get_user_repository),
):
    try:
        updates = request.model_dump(exclude_none=True)
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")

        await repo.update_user_by_device_id(user.device_id, updates)

        return BaseResponse(
            success=True,
            message="User profile updated successfully",
            data={"device_id": user.device_id, "updates": updates},
        )
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"{e}")


class _ConsumerPowerupRequest(BaseModel):
    fish_out: int = 0
    reveal_letter: int = 0
    ai_meaning: int = 0


@auth_router.post("/consume-powerups", response_model=BaseResponse)
async def consume_power_ups(
    payload: _ConsumerPowerupRequest,
    user: WordleUser = Depends(get_current_user),
    repo: UserRepository = Depends(get_user_repository),
):
    """
    Consume (decrement) powerups that were used while playing the offline game.
    Example payload:
    {
        "fish_out": 1,
        "reveal_letter": 2,
        "ai_meaning": 0
    }
    """
    try:
        # Get user’s current powerup counts from DB
        current_user = await repo.get_user_by_device_id(
            user.device_id, bypass_cache=True
        )
        if not current_user:
            raise HTTPException(status_code=404, detail="User not found")

        # Build updates dictionary
        updates = {}
        for field, decrement_by in payload.model_dump(exclude_none=True).items():
            if decrement_by > 0:
                current_value = current_user.get(field, 0)
                if current_value <= 0:
                    raise HTTPException(
                        status_code=400,
                        detail=f"User has no remaining '{field}' powerups to consume",
                    )

                # Never go below zero
                new_value = max(0, current_value - decrement_by)
                updates[field] = new_value

        if not updates:
            raise HTTPException(
                status_code=400, detail="No valid powerup consumption data"
            )

        # Persist changes in DB and invalidate cache
        await repo.update_user_by_device_id(user.device_id, updates)

        return BaseResponse(
            success=True,
            message="Powerups updated successfully",
            data={"device_id": user.device_id, "new_values": updates},
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")


@auth_router.get("/add-offline-earned-xp", response_model=BaseResponse)
async def add_offline_earned_xp(
    score: int,
    user: WordleUser = Depends(get_current_user),
    repo: UserRepository = Depends(get_user_repository),
):
    """
    Add XP earned from an offline game based on the given score.
    Example request: /add-offline-earned-xp?score=350
    """

    def _calculate_earned_xp(score: int) -> int:
        if score <= 0:
            return 0

        base_xp = 10

        if score <= 100:
            xp = base_xp + int(score * 0.5)
        elif score <= 500:
            xp = base_xp + int(100 * 0.5 + (score - 100) * 0.25)
        else:
            xp = base_xp + int(100 * 0.5 + 400 * 0.25 + (score - 500) * 0.1)

        return min(xp, 1000)

    try:
        # Fetch the latest user record
        current_user = await repo.get_user_by_device_id(
            user.device_id, bypass_cache=True
        )
        if not current_user:
            raise HTTPException(status_code=404, detail="User not found")

        # Calculate earned XP
        earned_xp = _calculate_earned_xp(score)

        # Compute new total XP (assume 'xp' field in users table)
        current_xp = current_user.get("xp", 0)
        new_xp = current_xp + earned_xp

        # Update the user’s XP in the DB
        await repo.update_user_by_device_id(user.device_id, {"xp": new_xp})

        return BaseResponse(
            success=True,
            message="XP updated successfully",
            data={
                "device_id": user.device_id,
                "earned_xp": earned_xp,
                "total_xp": new_xp,
            },
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")


@auth_router.get("/by-device/{device_id}", response_model=BaseResponse)
async def get_user_by_device_id(
    device_id: str,
    db=Depends(get_mysql_manager),
    redis=Depends(get_redis),
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
