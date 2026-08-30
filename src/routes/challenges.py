from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, Query
from typing import List, Optional
import json

from src.fcm_service import FCMService, get_fcm_service
from src.core.models.challenge import Challenge
from src.core.models.user import User
from src.core.repository import Repository, GetRepository
from src.core import BaseResponse, APITags, QueryOptions
from src.routes.auth import get_current_user
from pydantic import BaseModel, Field

challenges_router = APIRouter(prefix="/challenges", tags=[APITags.CHALLENGES])


class CreateChallengeRequest(BaseModel):
    p2_id: str
    p1_secret_words: List[str]
    turn_time_limit: Optional[int] = 120


@challenges_router.post("", response_model=BaseResponse[Challenge])
async def create_challenge(
    request: CreateChallengeRequest,
    bg: BackgroundTasks,
    user: User = Depends(get_current_user),
    user_repo: Repository[User] = Depends(GetRepository(User)),
    repo: Repository[Challenge] = Depends(GetRepository(Challenge)),
    fcm: FCMService = Depends(get_fcm_service),
):
    try:
        p2 = await user_repo.get(id=request.p2_id)
        if not p2:
            raise HTTPException(status_code=404, detail="Player 2 not found")

        challenge_entity = Challenge(
            p1_id=user.id,
            p2_id=p2.id,
            p1_username=user.username,
            p2_username=p2.username,
            p1_avatar=user.avatar,
            p2_avatar=p2.avatar,
            p1_secret_words=json.dumps(request.p1_secret_words),
            word_length=len(request.p1_secret_words[0]) if request.p1_secret_words else 4,
            turn_time_limit=request.turn_time_limit or 120,
        )

        created = await repo.add(challenge_entity)

        if p2.device_reg_token:
            bg.add_task(
                fcm.send,
                token=p2.device_reg_token,
                data={
                    "type": "challenge_invite",
                    "challenge_id": str(created.id),
                },
            )

        return BaseResponse(message="Challenge created", data=created)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {e}")


@challenges_router.get("/{challenge_id}", response_model=BaseResponse[Challenge])
async def get_challenge(
    challenge_id: str,
    repo: Repository[Challenge] = Depends(GetRepository(Challenge)),
):
    challenge = await repo.get(id=challenge_id)
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")
    return BaseResponse(message="Challenge fetched", data=challenge)
