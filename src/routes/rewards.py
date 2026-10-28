import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Header, Query, Path, status
from pydantic import BaseModel, Field
from sqlmodel import select, col
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy import update

from src.core.api_tags import APITags
from src.core.base_response import BaseResponse
from src.core.models.reward import Reward
from src.core.models.user import User
from src.core.repository import Repository, GetRepository
from src.core.services.reward_service import RewardService, get_reward_service
from src.core.utils.time import get_current_time
from src.database.db_connection_manager import get_async_session
from src.core.dependencies import get_optional_user, get_current_user



logger = logging.getLogger(__name__)

rewards_router = APIRouter(prefix="/rewards", tags=[APITags.REWARDS])


class MarkAsReadRequest(BaseModel):
    reward_ids: Optional[List[str]] = None
    user_id: Optional[str] = None


@rewards_router.get(
    "/unread",
    response_model=BaseResponse[List[Reward]],
    summary="List unread rewards for the current user",
)
async def list_unread_rewards(
    user_id: Optional[str] = Query(None, description="Target user ID (falls back to auth headers)"),
    limit: Optional[int] = Query(None, ge=1, le=100),
    offset: Optional[int] = Query(None, ge=0),
    current_user: Optional[User] = Depends(get_optional_user),
    session: AsyncSession = Depends(get_async_session),
) -> BaseResponse[List[Reward]]:
    target_user_id = user_id or (current_user.id if current_user else None)
    if not target_user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User ID is required via header (X-User-ID or user-id) or query parameter 'user_id'",
        )

    try:
        stmt = (
            select(Reward)
            .where(Reward.user_id == target_user_id, Reward.is_read == False)
            .order_by(col(Reward.created_at).desc())
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        if offset is not None:
            stmt = stmt.offset(offset)

        result = await session.exec(stmt)
        rewards = list(result.all())
        return BaseResponse(
            success=True,
            message="Unread rewards fetched successfully",
            data=rewards,
        )
    except Exception as e:
        logger.error(f"Failed to fetch unread rewards: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to fetch unread rewards: {e}")


@rewards_router.patch(
    "/{reward_id}/read",
    response_model=BaseResponse[Reward],
    summary="Mark a specific reward as read (PATCH)",
)
async def mark_reward_as_read(
    reward_id: str = Path(..., description="Reward ID to mark as read"),
    current_user: Optional[User] = Depends(get_optional_user),
    service: RewardService = Depends(get_reward_service),
) -> BaseResponse[Reward]:
    try:
        user_id = current_user.id if current_user else None
        updated_reward = await service.mark_as_read(reward_id=reward_id, user_id=user_id)
        if not updated_reward:
            # Check if it exists for another user to give a clearer error
            existing = await service.get_by_id(reward_id)
            if existing and user_id and existing.user_id != user_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="You are not authorized to mark this reward as read",
                )
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reward not found")

        return BaseResponse(
            success=True,
            message="Reward marked as read successfully",
            data=updated_reward,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to mark reward as read: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to mark reward as read: {e}")


@rewards_router.post(
    "/mark-as-read",
    response_model=BaseResponse[dict],
    summary="Mark one or multiple rewards as read",
)
async def mark_rewards_as_read(
    payload: MarkAsReadRequest,
    current_user: Optional[User] = Depends(get_current_user),
    service: RewardService = Depends(get_reward_service),
    session: AsyncSession = Depends(get_async_session),
) -> BaseResponse[dict]:
    try:
        target_user_id = payload.user_id or (current_user.id if current_user else None)
        marked_count = 0

        if payload.reward_ids:
            stmt = (
                update(Reward)
                .where(
                    col(Reward.id).in_(payload.reward_ids),
                    col(Reward.user_id) == target_user_id,
                )
                .values(is_read=True, updated_at=get_current_time())
            )
            result = await session.exec(stmt)
            await session.commit()
            marked_count = result.rowcount or 0

        return BaseResponse(
            success=True,
            message="Rewards marked as read",
            data={"marked_count": marked_count},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to mark rewards as read: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to mark rewards as read: {e}")

