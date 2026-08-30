from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
import logging

from src.core.api_tags import APITags
from src.core.base_response import BaseResponse
from src.core.query_options import QueryOptions
from src.core.models.lobby import Lobby
from src.core.models.user import User
from src.core.repository import Repository, GetRepository
from src.game import GameManager, get_game_manager, GameSettings

logger = logging.getLogger(__name__)

lobbies_router = APIRouter(prefix="/lobbies", tags=[APITags.GAMES])


class JoinLobbyRequest(BaseModel):
    code: str = Field(..., min_length=4, max_length=4, description="4-character lobby code")
    words: List[str] = Field(..., min_items=1, description="List of secret words")
    turn_time_limit: Optional[int] = Field(
        120, ge=1, description="Turn time limit in seconds (optional, only used by P1)"
    )


class JoinLobbyResponse(BaseModel):
    session_id: Optional[str] = Field(
        None, description="Game session ID if lobby is ready, None if waiting for P2"
    )
    lobby: Lobby = Field(..., description="The lobby information")
    is_host: bool = Field(..., description="Whether the user is the host (P1)")
    is_ready: bool = Field(..., description="Whether the lobby is ready to start")


@lobbies_router.post("/join", response_model=BaseResponse[JoinLobbyResponse])
async def join_lobby(
    request: JoinLobbyRequest,
    user_id: str,
    lobbies_repo: Repository[Lobby] = Depends(GetRepository(Lobby)),
    user_repo: Repository[User] = Depends(GetRepository(User)),
    game_manager: GameManager = Depends(get_game_manager),
) -> BaseResponse[JoinLobbyResponse]:
    try:
        user = await user_repo.get(id=user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        active_session = await game_manager.get_player_game_session(user.id)
        if active_session:
            logger.info(f"User {user.username} is already in game {active_session.session_id}. Ending previous game.")
            await game_manager.end_game(
                session_id=active_session.session_id,
                reason="Player joined a new lobby",
                should_broadcast=True,
            )

        if not request.words:
            raise HTTPException(status_code=400, detail="Words list cannot be empty")

        word_lengths = [len(w) for w in request.words]
        if len(set(word_lengths)) != 1:
            raise HTTPException(status_code=400, detail="All words must be the same length")

        word_length = word_lengths[0]
        rounds = len(request.words)
        words_str = ",".join(request.words) + ","

        lobby = await lobbies_repo.get(options=QueryOptions(filters={"code": request.code}))
        session_id = None
        is_host = False

        if not lobby:
            lobby_entity = Lobby(
                code=request.code,
                p1_id=user.id,
                p1_words=words_str,
                turn_time_limit=request.turn_time_limit or 120,
                word_length=word_length,
                rounds=rounds,
            )
            lobby = await lobbies_repo.add(lobby_entity)
            is_host = True
        else:
            if lobby.p1_id == user.id:
                lobby = await lobbies_repo.update(lobby, {"p1_words": words_str})
                is_host = True
            elif lobby.p2_id is None:
                if len(request.words) != lobby.rounds:
                    raise HTTPException(
                        status_code=400,
                        detail=f"You must provide {lobby.rounds} words to match lobby settings",
                    )
                if word_length != lobby.word_length:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Words must be {lobby.word_length} letters long to match lobby settings",
                    )

                lobby = await lobbies_repo.update(lobby, {"p2_id": user.id, "p2_words": words_str})
                is_host = False

                p1_user = await user_repo.get(id=lobby.p1_id)
                p2_user = await user_repo.get(id=lobby.p2_id)

                if not p1_user or not p2_user:
                    raise HTTPException(status_code=500, detail="Failed to fetch player data")

                game_session = await game_manager.create_game(
                    player1_user=p1_user,
                    player2_user=p2_user,
                    player1_secret_words=[w for w in lobby.p1_words.split(",") if w],
                    player2_secret_words=[w for w in (lobby.p2_words or "").split(",") if w],
                    settings=GameSettings(
                        rounds=lobby.rounds,
                        word_length=lobby.word_length,
                        turn_time_limit=lobby.turn_time_limit,
                        versusAi=False,
                    ),
                )
                session_id = game_session.session_id
                lobby = await lobbies_repo.update(lobby, {"session_id": session_id})
            elif lobby.p2_id == user.id:
                lobby = await lobbies_repo.update(lobby, {"p2_words": words_str})
                is_host = False
            else:
                raise HTTPException(status_code=400, detail="Lobby is full")

        response = JoinLobbyResponse(
            session_id=session_id,
            lobby=lobby,
            is_host=is_host,
            is_ready=bool(lobby.p1_id and lobby.p2_id),
        )

        return BaseResponse(
            message="Lobby joined successfully" if not is_host else "Lobby created successfully",
            data=response,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error joining lobby: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@lobbies_router.get("/{code}", response_model=BaseResponse[Lobby])
async def get_lobby(
    code: str,
    lobbies_repo: Repository[Lobby] = Depends(GetRepository(Lobby)),
) -> BaseResponse[Lobby]:
    try:
        lobby = await lobbies_repo.get(options=QueryOptions(filters={"code": code}))
        if not lobby:
            raise HTTPException(status_code=404, detail="Lobby not found")

        return BaseResponse(
            message="Lobby found",
            data=lobby,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting lobby: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@lobbies_router.delete("/{code}", response_model=BaseResponse[bool])
async def delete_lobby(
    code: str,
    user_id: str,
    lobbies_repo: Repository[Lobby] = Depends(GetRepository(Lobby)),
    user_repo: Repository[User] = Depends(GetRepository(User)),
) -> BaseResponse[bool]:
    try:
        user = await user_repo.get(id=user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        lobby = await lobbies_repo.get(options=QueryOptions(filters={"code": code}))
        if not lobby:
            raise HTTPException(status_code=404, detail="Lobby not found")

        if lobby.p1_id != user.id:
            raise HTTPException(
                status_code=403, detail="Only the lobby host can delete the lobby"
            )

        success = await lobbies_repo.delete(lobby)

        return BaseResponse(
            message="Lobby deleted successfully",
            data=success,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting lobby: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
