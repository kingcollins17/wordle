from typing import Optional, List
import time
from fastapi import APIRouter, Depends, HTTPException, Header, status
from pydantic import BaseModel, Field, model_validator

from src.core import BaseResponse, APITags, QueryOptions
from src.core.models.user import User
from src.core.repository import Repository, GetRepository
from src.core.dependencies import get_current_user

from src.core.services.reward_service import RewardService, get_reward_service

auth_router = APIRouter(prefix="/users", tags=[APITags.USERS])

# Request body schema for user creation
class CreateUserRequest(BaseModel):
    username: Optional[str] = Field(None, max_length=255)
    avatar: Optional[str] = None
    referral_code: Optional[str] = None


@auth_router.post("/", response_model=BaseResponse[User], status_code=status.HTTP_201_CREATED)
async def create_user(
    request: CreateUserRequest,
    repo: Repository[User] = Depends(GetRepository(User)),
    reward_service: RewardService = Depends(get_reward_service),
) -> BaseResponse[User]:
    # Check for existing username if provided
    if request.username:
        existing = await repo.get(options=QueryOptions(filters={"username": request.username}))
        if existing:
            raise HTTPException(status_code=400, detail="Username already taken")

    referrer = None
    if request.referral_code:
        referrer = await repo.get(options=QueryOptions(filters={"referral_code": request.referral_code.strip()}))
        if not referrer:
            raise HTTPException(status_code=400, detail="Invalid referral code")

    user_entity = User(
        # pyrefly: ignore [bad-argument-type]
        username=request.username,
        avatar=request.avatar,
        xp=10,
        coins=500,
        games_played=0,
        referrer_id=referrer.id if referrer else None,
    )

    created_user = await repo.add(user_entity)

    if referrer:
        await reward_service.reward(
            user_id=referrer.id,
            coins=100,
            title="Referral Bonus",
            description=f"Reward for referring {created_user.username or 'a new user'}",
        )

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


class SyncOfflineUsageRequest(BaseModel):
    fish_out: int = Field(default=0, ge=0)
    reveal_letter: int = Field(default=0, ge=0)
    word_meaning: int = Field(default=0, ge=0)
    coins_earned: int = Field(default=0, ge=0)
    xp_earned: int = Field(default=0, ge=0)


_ConsumerPowerupRequest = SyncOfflineUsageRequest


@auth_router.post("/sync-offline-usage", response_model=BaseResponse[User])
async def sync_offline_usage(
    payload: SyncOfflineUsageRequest,
    current_user: User = Depends(get_current_user),
    repo: Repository[User] = Depends(GetRepository(User)),
) -> BaseResponse[User]:
    """
    Sync offline gameplay usage:
    - Deduct powerups consumed during offline play.
    - Add coins and XP earned during offline play.
    """
    try:
        updates = {}

        # Deduct powerups
        for field in ("fish_out", "reveal_letter", "word_meaning"):
            decrement_by = getattr(payload, field, 0)
            if decrement_by > 0:
                current_value = getattr(current_user, field, 0) or 0
                if current_value < decrement_by:
                    raise HTTPException(
                        status_code=400,
                        detail=f"User has insufficient '{field}' powerups to consume",
                    )
                updates[field] = current_value - decrement_by

        # Add earned rewards
        if payload.coins_earned > 0:
            updates["coins"] = (current_user.coins or 0) + payload.coins_earned

        if payload.xp_earned > 0:
            updates["xp"] = (current_user.xp or 0) + payload.xp_earned

        if updates:
            updated_user = await repo.update(current_user, updates)
        else:
            updated_user = current_user

        return BaseResponse(
            success=True,
            message="Offline usage synced successfully",
            data=updated_user,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")


class ClaimDailyBonusRequest(BaseModel):
    amount: Optional[int] = Field(default=None, ge=1, description="Amount of coins to claim as daily bonus")
    coins: Optional[int] = Field(default=None, ge=1, description="Alias for amount of coins")

    @model_validator(mode="after")
    def validate_bonus_amount(self):
        if self.amount is None and self.coins is None:
            raise ValueError("Bonus coin amount is required and must be greater than 0")
        if self.amount is None and self.coins is not None:
            self.amount = self.coins
        return self


@auth_router.post("/claim-daily-bonus", response_model=BaseResponse[User])
@auth_router.post("/daily-bonus", response_model=BaseResponse[User])
async def claim_daily_bonus(
    payload: ClaimDailyBonusRequest,
    current_user: User = Depends(get_current_user),
    repo: Repository[User] = Depends(GetRepository(User)),
) -> BaseResponse[User]:
    """
    Claim daily bonus and increment user's coins based on client-specified amount.
    """
    try:
        bonus_coins = payload.amount or 0
        new_coins = (current_user.coins or 0) + bonus_coins

        updated_user = await repo.update(current_user, {"coins": new_coins})

        return BaseResponse(
            success=True,
            message=f"Daily bonus of {bonus_coins} coins claimed successfully",
            data=updated_user,
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
