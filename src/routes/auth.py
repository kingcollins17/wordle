from typing import Optional, List
import time
from fastapi import APIRouter, Depends, HTTPException, Header, status
from pydantic import BaseModel, Field

from src.core import BaseResponse, APITags, QueryOptions
from src.core.models.user import User
from src.core.repository import Repository, GetRepository

auth_router = APIRouter(prefix="/users", tags=[APITags.USERS])


async def get_current_user(
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    user_id: Optional[str] = Header(None, alias="user-id"),
    repo: Repository[User] = Depends(GetRepository(User)),
) -> User:
    uid = x_user_id or user_id
    if not uid:
        raise HTTPException(status_code=401, detail="User ID header required (X-User-ID or user-id)")
    user = await repo.get(id=uid)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# Request body schema for user creation
class CreateUserRequest(BaseModel):
    username: Optional[str] = Field(None, max_length=255)
    avatar: Optional[str] = None


@auth_router.post("/", response_model=BaseResponse[User], status_code=status.HTTP_201_CREATED)
async def create_user(
    request: CreateUserRequest,
    repo: Repository[User] = Depends(GetRepository(User)),
) -> BaseResponse[User]:
    # Check for existing username if provided
    if request.username:
        existing = await repo.get(options=QueryOptions(filters={"username": request.username}))
        if existing:
            raise HTTPException(status_code=400, detail="Username already taken")

    user_entity = User(
        # pyrefly: ignore [bad-argument-type]
        username=request.username,
        avatar=request.avatar,
        xp=10,
        coins=500,
        games_played=0,
    )

    created_user = await repo.add(user_entity)

    return BaseResponse(
        success=True,
        message="User created successfully",
        data=created_user,
    )


class UpdateUserRequest(BaseModel):
    username: Optional[str] = Field(None, max_length=255)
    avatar: Optional[str] = Field(None)


@auth_router.put("/update-profile/{user_id}", response_model=BaseResponse[User])
async def update_user_profile(
    user_id: str,
    request: UpdateUserRequest,
    repo: Repository[User] = Depends(GetRepository(User)),
) -> BaseResponse[User]:
    try:
        user = await repo.get(id=user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        updates = request.model_dump(exclude_none=True)
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")

        if "username" in updates and updates["username"] != user.username:
            existing = await repo.get(options=QueryOptions(filters={"username": updates["username"]}))
            if existing:
                raise HTTPException(status_code=400, detail="Username already taken")

        updated_user = await repo.update(user, updates)

        return BaseResponse(
            success=True,
            message="User profile updated successfully",
            data=updated_user,
        )
    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=f"{e}")


class _ConsumerPowerupRequest(BaseModel):
    fish_out: int = 0
    reveal_letter: int = 0
    word_meaning: int = 0


@auth_router.post("/consume-powerups/{user_id}", response_model=BaseResponse[User])
async def consume_power_ups(
    user_id: str,
    payload: _ConsumerPowerupRequest,
    repo: Repository[User] = Depends(GetRepository(User)),
) -> BaseResponse[User]:
    """
    Consume (decrement) powerups that were used while playing the game.
    """
    try:
        user = await repo.get(id=user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        updates = {}
        for field, decrement_by in payload.model_dump(exclude_none=True).items():
            if decrement_by > 0:
                current_value = getattr(user, field, 0)
                if current_value < decrement_by:
                    raise HTTPException(
                        status_code=400,
                        detail=f"User has insufficient '{field}' powerups to consume",
                    )
                updates[field] = current_value - decrement_by

        if not updates:
            raise HTTPException(
                status_code=400, detail="No valid powerup consumption data"
            )

        updated_user = await repo.update(user, updates)

        return BaseResponse(
            success=True,
            message="Powerups updated successfully",
            data=updated_user,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")


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


class OfflineEarnedXpResponse(BaseModel):
    user: User
    earned_xp: int
    total_xp: int


@auth_router.get("/add-offline-earned-xp/{user_id}", response_model=BaseResponse[OfflineEarnedXpResponse])
async def add_offline_earned_xp(
    user_id: str,
    score: int,
    repo: Repository[User] = Depends(GetRepository(User)),
) -> BaseResponse[OfflineEarnedXpResponse]:
    """
    Add XP earned from an offline game based on the given score.
    """
    try:
        user = await repo.get(id=user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        earned_xp = _calculate_earned_xp(score)
        new_xp = user.xp + earned_xp

        updated_user = await repo.update(user, {"xp": new_xp})

        return BaseResponse(
            success=True,
            message="XP updated successfully",
            data=OfflineEarnedXpResponse(
                user=updated_user,
                earned_xp=earned_xp,
                total_xp=new_xp,
            ),
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")





@auth_router.get("/by-id/{user_id}", response_model=BaseResponse[User])
async def get_user_by_id(
    user_id: str,
    repo: Repository[User] = Depends(GetRepository(User)),
) -> BaseResponse[User]:
    user = await repo.get(id=user_id)
   

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return BaseResponse(
        success=True,
        message="User fetched successfully",
        data=user,
    )


@auth_router.get("/update-reg-token/{user_id}", response_model=BaseResponse[User])
async def update_device_reg_token(
    user_id: str,
    device_reg_token: str,
    repo: Repository[User] = Depends(GetRepository(User)),
) -> BaseResponse[User]:
    try:
        if not device_reg_token:
            raise HTTPException(status_code=400, detail="device_reg_token is required")

        user = await repo.get(id=user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        updated_user = await repo.update(user, {"device_reg_token": device_reg_token})

        return BaseResponse(
            success=True,
            message="Device registration token updated successfully",
            data=updated_user,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class UserListResponse(BaseModel):
    users: List[User]
    query_time_seconds: float


@auth_router.get("/list-users", response_model=BaseResponse[UserListResponse])
async def list_users(
    q: Optional[str] = None,
    page: int = 1,
    per_page: int = 50,
    repo: Repository[User] = Depends(GetRepository(User)),
) -> BaseResponse[UserListResponse]:
    """
    Search for users by username or list all users paginated.
    """
    limit = per_page
    offset = (page - 1) * per_page
    start_time = time.monotonic()

    options = QueryOptions(limit=limit, offset=offset)
    if q:
        # pyrefly: ignore [missing-attribute]
        options.where = [User.username.ilike(f"%{q}%")]

    users = await repo.get_many(options=options)
    elapsed = time.monotonic() - start_time

    if not users:
        raise HTTPException(status_code=404, detail="No users matched the pattern")

    return BaseResponse(
        success=True,
        message="Users fetched successfully",
        data=UserListResponse(users=users, query_time_seconds=round(elapsed, 6)),
    )
