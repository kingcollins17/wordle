from datetime import datetime
from typing import Optional, List
import time
from fastapi import APIRouter, Depends, HTTPException, Header, Response, status
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


class SyncOfflineUserRequest(BaseModel):
    id: Optional[str] = Field(None, description="Offline client-generated user ID (UUID)")
    user_id: Optional[str] = Field(None, description="Alias for id")
    username: Optional[str] = Field(None, max_length=255, description="Username chosen by the user")
    avatar: Optional[str] = Field(None, description="Avatar URL or identifier")
    device_reg_token: Optional[str] = Field(None, description="Device push notification token")
    xp: Optional[int] = Field(None, ge=0, description="Total XP accumulated offline")
    coins: Optional[int] = Field(None, ge=0, description="Total coins accumulated/remaining offline")
    games_played: Optional[int] = Field(None, ge=0, description="Total games played offline")
    reveal_letter: Optional[int] = Field(None, ge=0, description="Reveal letter power-ups balance")
    fish_out: Optional[int] = Field(None, ge=0, description="Fish out power-ups balance")
    word_meaning: Optional[int] = Field(None, ge=0, description="Word meaning power-ups balance")
    referral_code: Optional[str] = Field(None, description="Referral code of the referrer or entered on sign-up")
    referrer_code: Optional[str] = Field(None, description="Explicit alias for referral code of the referrer")
    user_referral_code: Optional[str] = Field(None, description="Own referral code if generated offline")
    created_at: Optional[datetime] = Field(None, description="Original offline creation timestamp")

    @model_validator(mode="after")
    def populate_id(self):
        if not self.id and self.user_id:
            self.id = self.user_id
        return self


@auth_router.post("/sync-offline-user", response_model=BaseResponse[User], status_code=status.HTTP_201_CREATED)
@auth_router.post("/sync-offline", response_model=BaseResponse[User], status_code=status.HTTP_201_CREATED)
async def sync_offline_user(
    request: SyncOfflineUserRequest,
    response: Response,
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    user_id_header: Optional[str] = Header(None, alias="user-id"),
    repo: Repository[User] = Depends(GetRepository(User)),
    reward_service: RewardService = Depends(get_reward_service),
) -> BaseResponse[User]:
    """
    Sync a user created locally while offline to the backend database.
    Handles idempotency (re-syncing with existing ID updates user stats if changed)
    and awards referrer bonuses if a referral code is provided.
    """
    uid = (request.id or x_user_id or user_id_header or "").strip() or None

    # Idempotent check: if user already exists by ID
    if uid:
        existing_user = await repo.get(id=uid)
        if existing_user:
            updates = {}
            if request.username and request.username != existing_user.username:
                user_with_name = await repo.get(options=QueryOptions(filters={"username": request.username}))
                if user_with_name and user_with_name.id != existing_user.id:
                    raise HTTPException(status_code=400, detail="Username already taken")
                updates["username"] = request.username

            if request.avatar and request.avatar != existing_user.avatar:
                updates["avatar"] = request.avatar
            if request.device_reg_token and request.device_reg_token != existing_user.device_reg_token:
                updates["device_reg_token"] = request.device_reg_token
            if request.xp is not None and request.xp > (existing_user.xp or 0):
                updates["xp"] = request.xp
            if request.coins is not None and request.coins > (existing_user.coins or 0):
                updates["coins"] = request.coins
            if request.games_played is not None and request.games_played > (existing_user.games_played or 0):
                updates["games_played"] = request.games_played
            if request.reveal_letter is not None:
                updates["reveal_letter"] = request.reveal_letter
            if request.fish_out is not None:
                updates["fish_out"] = request.fish_out
            if request.word_meaning is not None:
                updates["word_meaning"] = request.word_meaning

            if updates:
                existing_user = await repo.update(existing_user, updates)

            response.status_code = status.HTTP_200_OK
            return BaseResponse(
                success=True,
                message="User already synced successfully",
                data=existing_user,
            )

    # Check for username conflict with another user
    if request.username:
        user_with_name = await repo.get(options=QueryOptions(filters={"username": request.username}))
        if user_with_name and (not uid or user_with_name.id != uid):
            raise HTTPException(status_code=400, detail="Username already taken")

    # Resolve referrer
    referrer = None
    ref_code = (request.referrer_code or request.referral_code or "").strip()
    if ref_code:
        potential_referrer = await repo.get(options=QueryOptions(filters={"referral_code": ref_code}))
        if potential_referrer and (not uid or potential_referrer.id != uid):
            referrer = potential_referrer
        elif request.referrer_code:
            raise HTTPException(status_code=400, detail="Invalid referral code")

    # Build user entity
    user_data = {
        "username": request.username,
        "avatar": request.avatar,
        "device_reg_token": request.device_reg_token,
        "xp": request.xp if request.xp is not None else 10,
        "coins": request.coins if request.coins is not None else 500,
        "games_played": request.games_played if request.games_played is not None else 0,
        "reveal_letter": request.reveal_letter if request.reveal_letter is not None else 1,
        "fish_out": request.fish_out if request.fish_out is not None else 1,
        "word_meaning": request.word_meaning if request.word_meaning is not None else 1,
        "referrer_id": referrer.id if referrer else None,
    }
    if uid:
        user_data["id"] = uid
    if request.user_referral_code:
        code_exists = await repo.get(options=QueryOptions(filters={"referral_code": request.user_referral_code.strip()}))
        if not code_exists:
            user_data["referral_code"] = request.user_referral_code.strip()
    if request.created_at is not None:
        # pyrefly: ignore[bad-assignment]
        user_data["created_at"] = request.created_at

    # pyrefly: ignore[bad-argument-type]
    user_entity = User(**user_data)
    created_user = await repo.add(user_entity)

    # Award referral bonus
    if referrer:
        await reward_service.reward(
            user_id=referrer.id,
            coins=100,
            title="Referral Bonus",
            description=f"Reward for referring {created_user.username or 'a new user'}",
        )

    return BaseResponse(
        success=True,
        message="Offline user synced successfully",
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
