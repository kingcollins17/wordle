from fastapi import APIRouter, Depends, Query, HTTPException
from typing import Optional, List, Dict
from pydantic import BaseModel, Field
import random


from src.core import *
from src.models.wordle_user import WordleUser
from ..repositories.user_repository import UserRepository, get_user_repository

lb_router = APIRouter(prefix="/leaderboards", tags=[APITags.LEADERBOARD])


class LeaderboardRank(BaseModel):
    device_id: str
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
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(100, ge=1, le=100, description="Items per page (max 100)"),
    user_repo: UserRepository = Depends(get_user_repository),
    device_id: str = Query(..., description="Device ID of the current user"),
):
    """
    Get the XP leaderboard with accurate ranking and current user position.

    Returns:
    - paginated top users (max 100 per page)
    - current user's position (even if not in current page)
    - total user count
    """
    try:
        # Get current user and validate
        current_user = await user_repo.get_user_by_device_id(device_id=device_id)
        if not current_user:
            raise HTTPException(status_code=404, detail="User not found")

        current_user = WordleUser(**current_user)
        # Get all users sorted by XP (descending)
        all_users = await user_repo.list_users(order_by="xp", ascending=False)
        total_users = len(all_users)

        # Calculate current user's rank
        current_user_rank = next(
            (i + 1 for i, u in enumerate(all_users) if u.device_id == device_id),
            None,
        )

        # Calculate pagination
        offset = (page - 1) * per_page
        paginated_users = all_users[offset : offset + per_page]

        # Build leaderboard response
        leaderboard = [
            LeaderboardRank(
                device_id=user.device_id,
                username=user.username,
                xp=user.xp,
                rank=offset + i + 1,
                is_current_user=(user.device_id == device_id),
            )
            for i, user in enumerate(paginated_users)
        ]

        fake = generate_fake_leaderboard(25)
        leaderboard.extend(fake)
        leaderboard = sort_leaderboard_by_xp(leaderboard)
        # Prepare current user data if not in current page
        current_user_data = None
        if current_user_rank and not any(u.is_current_user for u in leaderboard):
            current_user_data = LeaderboardRank(
                device_id=current_user.device_id,
                username=current_user.username,
                xp=current_user.xp,
                rank=current_user_rank,
                is_current_user=True,
            )

        return BaseResponse(
            message="Leaderboards",
            data=LeaderboardResponse(
                top_users=leaderboard,
                current_user=current_user_data,
                total_users=total_users,
                page=page,
                per_page=per_page,
            ),
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to fetch leaderboard: {str(e)}"
        )


def generate_fake_leaderboard(count: int = 30) -> List[LeaderboardRank]:
    """
    Generates fake leaderboard data without sorting or ranking
    """

    count = min(count, 30)
    return [
        LeaderboardRank(
            device_id=f"device_{random.randint(100000, 999999)}",
            username=usernames[i],
            xp=random.randint(100, 3000),
            rank=0,  # Rank left as 0 since we're not calculating it
            is_current_user=False,
        )
        for i in range(count)
    ]


def sort_leaderboard_by_xp(leaderboard: List[LeaderboardRank]) -> List[LeaderboardRank]:
    """
    Sorts a leaderboard by XP in descending order and updates ranks

    Args:
        leaderboard: List of LeaderboardRank objects to be sorted

    Returns:
        New sorted list with updated ranks
    """
    # Sort by XP descending
    sorted_list = sorted(leaderboard, key=lambda x: x.xp, reverse=True)

    # Update ranks based on new order
    for rank, user in enumerate(sorted_list, start=1):
        user.rank = rank

    return sorted_list
