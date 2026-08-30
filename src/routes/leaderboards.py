from fastapi import APIRouter, Depends, Query, HTTPException
from typing import Optional, List
from pydantic import BaseModel, Field

from src.core import BaseResponse, APITags, QueryOptions
from src.core.models.user import User
from src.core.repository import Repository, GetRepository

lb_router = APIRouter(prefix="/leaderboards", tags=[APITags.LEADERBOARD])


class LeaderboardRank(BaseModel):
    user_id: str
    username: Optional[str]
    xp: int = Field(...)
    rank: int = Field(...)
    is_current_user: bool = Field(default=False)


class LeaderboardResponse(BaseModel):
    top_users: List[LeaderboardRank]
    current_user: Optional[LeaderboardRank]
    total_users: int
    page: int
    per_page: int


@lb_router.get("/", response_model=BaseResponse[LeaderboardResponse])
async def get_xp_leaderboard(
    user_id: str = Query(..., description="User ID of the current user"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(100, ge=1, le=100, description="Items per page (max 100)"),
    user_repo: Repository[User] = Depends(GetRepository(User)),
):
    try:
        current_user = await user_repo.get(id=user_id)
        if not current_user:
            raise HTTPException(status_code=404, detail="User not found")

        # Get all users sorted by XP (descending)
        all_users = await user_repo.get_many(
            options=QueryOptions(order_by="xp", ascending=False)
        )
        total_users = len(all_users)

        # Calculate current user's rank
        current_user_rank = next(
            (i + 1 for i, u in enumerate(all_users) if u.id == user_id),
            None,
        )

        # Calculate pagination
        offset = (page - 1) * per_page
        paginated_users = all_users[offset : offset + per_page]

        # Build leaderboard response
        leaderboard = [
            LeaderboardRank(
                # pyrefly: ignore [bad-argument-type]
                user_id=u.id,
                username=u.username,
                xp=u.xp,
                rank=offset + i + 1,
                is_current_user=(u.id == user_id),
            )
            for i, u in enumerate(paginated_users)
        ]

        current_user_lb = (
            LeaderboardRank(
                user_id=current_user.id,
                username=current_user.username,
                xp=current_user.xp,
                rank=current_user_rank or 0,
                is_current_user=True,
            )
            if current_user_rank
            else None
        )

        return BaseResponse(
            success=True,
            message="Leaderboard fetched successfully",
            data=LeaderboardResponse(
                top_users=leaderboard,
                current_user=current_user_lb,
                total_users=total_users,
                page=page,
                per_page=per_page,
            ),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")
