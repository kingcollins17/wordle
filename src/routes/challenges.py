from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, Query
from typing import List, Optional
from firebase_admin import messaging

from src.fcm_service import FCMService, get_fcm_service
from src.game.lobby import LobbyManager, lobby_manager
from src.models.wordle_user import WordleUser
from src.core import BaseResponse, APITags
from src.repositories.user_repository import (
    get_current_user,
    UserRepository,
    get_user_repository,
)
from src.repositories.challenges_repository import (
    ChallengesRepository,
    get_challenges_repository,
)
from ..models.challenges_models import *

challenges_router = APIRouter(prefix="/challenges", tags=[APITags.CHALLENGES])


# ----------------------
# Challenges
# ----------------------


@challenges_router.post("", response_model=BaseResponse[Challenge])
async def create_challenge(
    challenge: ChallengeCreate,
    bg: BackgroundTasks,
    user: WordleUser = Depends(get_current_user),
    user_repo: UserRepository = Depends(get_user_repository),
    repo: ChallengesRepository = Depends(get_challenges_repository),
    fcm: FCMService = Depends(get_fcm_service),
    lobby_manager: LobbyManager = Depends(lobby_manager),
):
    """Create a new challenge and notify p2"""
    try:

        def _validate(value: Challenge):
            p1_secret_words = value.p1_secret_words
            assert p1_secret_words, "Secret words must not be empty"
            first = p1_secret_words[0]
            length = len(first)
            for i in p1_secret_words:
                assert len(i) == length, "Words cannot be of different lengths"

        _validate(challenge)  # validate challenge
        # Validate p2
        p2 = await user_repo.get_user_by_id(challenge.p2_id)
        if not p2:
            raise HTTPException(status_code=404, detail="Player 2 not found")
        p2 = WordleUser(**p2)

        created: Challenge = await repo.create_challenge(
            ChallengeCreate(
                p1_id=user.id,
                p2_id=p2.id,
                p1_username=user.username,
                p2_username=p2.username,
                p1_secret_words=challenge.p1_secret_words,
                p2_secret_words=None,
                word_length=len(challenge.p1_secret_words[0]),
                lobby_code=lobby_manager.generate_code(),
                turn_time_limit=challenge.turn_time_limit,
            ),
        )

        # Notify player 2 if they have a token
        if p2.device_reg_token:
            bg.add_task(
                fcm.send_to_token,
                token=p2.device_reg_token,
                data={
                    "type": "challenge_invite",
                    "app_url": "/accept-challenge",
                    "challenge_id": str(created.id),
                },
                notification=messaging.Notification(
                    title="New Challenge!",
                    body=f"{user.username} has challenged you to a game!",
                ),
            )

        return BaseResponse(message="Challenge created", data=created)
    except Exception as e:
        # import traceback

        # traceback.print_exc()

        raise HTTPException(status_code=500, detail=f"Error creating challenge: {e}")


@challenges_router.get("", response_model=BaseResponse[List[Challenge]])
async def list_challenges(
    user: WordleUser = Depends(get_current_user),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    repo: ChallengesRepository = Depends(get_challenges_repository),
):
    user_id = user.id
    limit = per_page
    offset = (page - 1) * per_page

    challenges = await repo.list_challenges_for_user(user_id, limit, offset)
    return BaseResponse(message="Challenges list", data=challenges)


@challenges_router.get(
    "/find/{challenge_id}",
    response_model=BaseResponse[Challenge],
)
async def find_challenge(
    challenge_id: int,
    user: WordleUser = Depends(get_current_user),
    repo: ChallengesRepository = Depends(get_challenges_repository),
):
    try:
        challenge = await repo.get_challenge_by_id(challenge_id)
        if not challenge:
            raise HTTPException(status_code=404, detail="Challenge not found")

        if challenge.p1_id != user.id and challenge.p2_id != user.id:
            raise HTTPException(
                status_code=403, detail="Not authorized to view this challenge"
            )

        return BaseResponse(message="Challenge found", data=challenge)
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error while finding challenge: {e}"
        )


@challenges_router.patch(
    "/update/{challenge_id}", response_model=BaseResponse[Challenge]
)
async def update_challenge(
    challenge_id: int,
    update: ChallengeUpdate,
    user: WordleUser = Depends(get_current_user),
    repo: ChallengesRepository = Depends(get_challenges_repository),
):
    challenge = await repo.get_challenge_by_id(challenge_id)
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")

    if challenge.p1_id != user.id and challenge.p2_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    updated = await repo.update_challenge(challenge_id, update)
    return BaseResponse(message="Challenge updated", data=updated)


class _AcceptChallengePayload(BaseModel):
    p2_secret_words: List[str]


@challenges_router.patch(
    "/accept/{challenge_id}", response_model=BaseResponse[Challenge]
)
async def accept_challenge(
    challenge_id: int,
    update: _AcceptChallengePayload,
    bg: BackgroundTasks,
    user: WordleUser = Depends(get_current_user),
    user_repo: UserRepository = Depends(get_user_repository),
    repo: ChallengesRepository = Depends(get_challenges_repository),
    fcm: FCMService = Depends(get_fcm_service),
):
    try:
        # Fetch challenge
        challenge = await repo.get_challenge_by_id(challenge_id)
        if not challenge:
            raise HTTPException(status_code=404, detail="Challenge not found")
        assert challenge.p1_secret_words and len(challenge.p1_secret_words) == len(
            update.p2_secret_words
        ), f"Your secret words must be {len(challenge.p1_secret_words)}"

        p1_secret_words = challenge.p1_secret_words

        length = len(p1_secret_words[0])
        for i in update.p2_secret_words:
            assert len(i) == length, f"Your secret words must be {length} letter words"

        # Ensure only p2 can accept
        if challenge.p2_id != user.id:
            raise HTTPException(
                status_code=403, detail="Only Player 2 can accept this challenge"
            )

        # Update challenge with p2's secret words
        updated = await repo.update_challenge(
            challenge_id,
            ChallengeUpdate(p2_secret_words=update.p2_secret_words),
        )

        # Get Player 1 (to notify them)
        p1 = await user_repo.get_user_by_id(challenge.p1_id)
        if not p1:
            raise HTTPException(status_code=404, detail="Player 1 not found")
        p1 = WordleUser(**p1)

        # Send FCM notification to Player 1 if token exists
        if p1.device_reg_token:
            bg.add_task(
                fcm.send_to_token,
                token=p1.device_reg_token,
                data={
                    "type": "challenge_accepted",
                    "app_url": "/start-game",
                    "challenge_id": str(updated.id),
                },
                notification=messaging.Notification(
                    title="Challenge Accepted!",
                    body=f"{user.username} accepted your challenge. Time to play!",
                ),
            )

        return BaseResponse(message="Challenge accepted", data=updated)
    except Exception as e:
        # import traceback

        # traceback.print_exc()
        raise HTTPException(
            status_code=400, detail=f"Error occurred while accepting challenge: {e}"
        )


@challenges_router.delete("/delete/{challenge_id}", response_model=BaseResponse[dict])
async def delete_challenge(
    challenge_id: int,
    user: WordleUser = Depends(get_current_user),
    repo: ChallengesRepository = Depends(get_challenges_repository),
):
    challenge = await repo.get_challenge_by_id(challenge_id)
    if not challenge:
        raise HTTPException(status_code=404, detail="Challenge not found")

    if challenge.p1_id != user.id and challenge.p2_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    deleted = await repo.delete_challenge(challenge_id)
    return BaseResponse(message="Challenge deleted", data={"id": challenge_id})
