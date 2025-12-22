# src/routes/lobbies.py

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.core.api_tags import APITags
from src.core.base_response import BaseResponse
from src.repositories.lobbies_repository import (
    LobbiesRepository,
    get_lobbies_repository,
)
from src.repositories.user_repository import UserRepository, get_user_repository
from src.game import GameManager, get_game_manager, GameSettings
from src.models.lobby import DatabaseLobby
from src.models.wordle_user import WordleUser
from src.models.game_session import GameSession
import logging

logger = logging.getLogger(__name__)

lobbies_router = APIRouter(prefix="/lobbies", tags=[APITags.GAMES])


class JoinLobbyRequest(BaseModel):
    """Request model for joining a lobby"""
    
    code: str = Field(..., min_length=4, max_length=4, description="4-character lobby code")
    words: List[str] = Field(..., min_items=1, description="List of secret words")
    turn_time_limit: Optional[int] = Field(
        120, 
        ge=1, 
        description="Turn time limit in seconds (optional, only used by P1)"
    )


class JoinLobbyResponse(BaseModel):
    """Response model for joining a lobby"""
    
    session_id: Optional[str] = Field(
        None, 
        description="Game session ID if lobby is ready, None if waiting for P2"
    )
    lobby: DatabaseLobby = Field(..., description="The lobby information")
    is_host: bool = Field(..., description="Whether the user is the host (P1)")
    is_ready: bool = Field(..., description="Whether the lobby is ready to start")


@lobbies_router.post("/join", response_model=BaseResponse[JoinLobbyResponse])
async def join_lobby(
    request: JoinLobbyRequest,
    device_id: str,
    lobbies_repo: LobbiesRepository = Depends(get_lobbies_repository),
    user_repo: UserRepository = Depends(get_user_repository),
    game_manager: GameManager = Depends(get_game_manager),
) -> BaseResponse[JoinLobbyResponse]:
    """
    Join or create a lobby with the given code.
    
    Behavior:
    - If lobby doesn't exist: Create new lobby with user as P1 (host)
    - If lobby exists and P1 is set but P2 is not: Join as P2 and create game
    - If lobby is full: Return error
    
    Args:
        request: Join lobby request with code, words, and optional turn_time_limit
        device_id: User's device ID (from auth)
        lobbies_repo: Lobbies repository dependency
        user_repo: User repository dependency
        game_manager: Game manager dependency
        
    Returns:
        BaseResponse containing JoinLobbyResponse with session_id (if ready) and lobby info
    """
    try:
        # Get user data
        user_data = await user_repo.get_user_by_device_id(device_id)
        if not user_data:
            raise HTTPException(status_code=404, detail="User not found")
        
        user = WordleUser(**user_data)
        
        # Validate words list
        if not request.words:
            raise HTTPException(status_code=400, detail="Words list cannot be empty")
        
        # Check word lengths are consistent
        word_lengths = [len(w) for w in request.words]
        if len(set(word_lengths)) != 1:
            raise HTTPException(
                status_code=400, 
                detail="All words must be the same length"
            )
        
        word_length = word_lengths[0]
        rounds = len(request.words)
        
        # Convert words list to comma-separated string
        words_str = ",".join(request.words) + ","
        
        # Try to find existing lobby
        lobby = await lobbies_repo.get_lobby_by_code(request.code)
        
        session_id = None
        is_host = False
        
        if not lobby:
            # Create new lobby with user as P1
            lobby_data = {
                "code": request.code,
                "p1_id": user_data["id"],
                "p1_device_id": device_id,
                "p1_words": words_str,
                "turn_time_limit": request.turn_time_limit or 120,
                "word_length": word_length,
                "rounds": rounds,
            }
            
            lobby_id = await lobbies_repo.create_lobby(lobby_data)
            lobby = await lobbies_repo.get_lobby_by_id(lobby_id)
            is_host = True
            
            logger.info(
                f"User {user.username} created lobby {request.code} as P1"
            )
            
        else:
            # Lobby exists
            if lobby.p1_id is None:
                # This shouldn't happen, but handle it
                raise HTTPException(
                    status_code=500, 
                    detail="Lobby exists but has no P1"
                )
            
            if lobby.p1_id == user_data["id"]:
                # User is trying to rejoin as P1
                # Update their words in case they changed
                await lobbies_repo.update_lobby(
                    request.code,
                    {
                        "p1_device_id": device_id,
                        "p1_words": words_str
                    }
                )
                lobby = await lobbies_repo.get_lobby_by_code(request.code)
                is_host = True
                
                logger.info(
                    f"User {user.username} updated their words in lobby {request.code}"
                )
                
            elif lobby.p2_id is None:
                # User is joining as P2
                # Validate that words match lobby settings
                if len(request.words) != lobby.rounds:
                    raise HTTPException(
                        status_code=400,
                        detail=f"You must provide {lobby.rounds} words to match lobby settings"
                    )
                
                if word_length != lobby.word_length:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Words must be {lobby.word_length} letters long to match lobby settings"
                    )
                
                # Update lobby with P2 data
                await lobbies_repo.update_lobby(
                    request.code,
                    {
                        "p2_id": user_data["id"],
                        "p2_device_id": device_id,
                        "p2_words": words_str,
                    }
                )
                
                lobby = await lobbies_repo.get_lobby_by_code(request.code)
                is_host = False
                
                logger.info(
                    f"User {user.username} joined lobby {request.code} as P2"
                )
                
                # Lobby is now ready, create game
                p1_user_data = await user_repo.get_user_by_id(lobby.p1_id)
                p2_user_data = await user_repo.get_user_by_id(lobby.p2_id)
                
                if not p1_user_data or not p2_user_data:
                    raise HTTPException(
                        status_code=500,
                        detail="Failed to fetch player data"
                    )
                
                p1_user = WordleUser(**p1_user_data)
                p2_user = WordleUser(**p2_user_data)
                
                # Create game session
                game_session = await game_manager.create_game(
                    player1_user=p1_user,
                    player2_user=p2_user,
                    player1_secret_words=lobby.get_p1_words_list(),
                    player2_secret_words=lobby.get_p2_words_list(),
                    settings=GameSettings(
                        rounds=lobby.rounds,
                        word_length=lobby.word_length,
                        turn_time_limit=lobby.turn_time_limit,
                        versusAi=False,
                    ),
                )
                
                session_id = game_session.session_id
                
                logger.info(
                    f"Game session {session_id} created for lobby {request.code}"
                )
                
                # Optionally delete the lobby after game creation
                # await lobbies_repo.delete_lobby(request.code)
                
            elif lobby.p2_id == user_data["id"]:
                # User is trying to rejoin as P2
                # Update their words in case they changed
                await lobbies_repo.update_lobby(
                    request.code,
                    {
                        "p2_device_id": device_id,
                        "p2_words": words_str
                    }
                )
                lobby = await lobbies_repo.get_lobby_by_code(request.code)
                is_host = False
                
                logger.info(
                    f"User {user.username} updated their words in lobby {request.code}"
                )
                
            else:
                # Lobby is full with different players
                raise HTTPException(
                    status_code=400,
                    detail="Lobby is full"
                )
        
        response = JoinLobbyResponse(
            session_id=session_id,
            lobby=lobby,
            is_host=is_host,
            is_ready=lobby.is_ready(),
        )
        
        return BaseResponse(
            message="Lobby joined successfully" if not is_host else "Lobby created successfully",
            data=response,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error joining lobby: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@lobbies_router.get("/{code}", response_model=BaseResponse[DatabaseLobby])
async def get_lobby(
    code: str,
    lobbies_repo: LobbiesRepository = Depends(get_lobbies_repository),
) -> BaseResponse[DatabaseLobby]:
    """
    Get lobby information by code.
    
    Args:
        code: The lobby code
        lobbies_repo: Lobbies repository dependency
        
    Returns:
        BaseResponse containing the lobby information
    """
    try:
        lobby = await lobbies_repo.get_lobby_by_code(code)
        
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
    device_id: str,
    lobbies_repo: LobbiesRepository = Depends(get_lobbies_repository),
    user_repo: UserRepository = Depends(get_user_repository),
) -> BaseResponse[bool]:
    """
    Delete a lobby. Only the host (P1) can delete the lobby.
    
    Args:
        code: The lobby code
        device_id: User's device ID (from auth)
        lobbies_repo: Lobbies repository dependency
        user_repo: User repository dependency
        
    Returns:
        BaseResponse indicating success
    """
    try:
        user_data = await user_repo.get_user_by_device_id(device_id)
        if not user_data:
            raise HTTPException(status_code=404, detail="User not found")
        
        lobby = await lobbies_repo.get_lobby_by_code(code)
        if not lobby:
            raise HTTPException(status_code=404, detail="Lobby not found")
        
        # Only P1 (host) can delete the lobby
        if lobby.p1_id != user_data["id"]:
            raise HTTPException(
                status_code=403,
                detail="Only the lobby host can delete the lobby"
            )
        
        affected = await lobbies_repo.delete_lobby(code)
        
        return BaseResponse(
            message="Lobby deleted successfully",
            data=affected > 0,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting lobby: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
