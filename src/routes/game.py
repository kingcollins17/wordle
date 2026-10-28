import logging
import random
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field
from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlalchemy import update as sqlalchemy_update

from src.core.api_tags import APITags
from src.core.base_response import BaseResponse
from src.core.models.game import Game, GameStatus, Player
from src.core.models.user import User
from src.core.models.word import Word
from src.core.query_options import QueryOptions
from src.core.repository import GetRepository, Repository
from src.database.db_connection_manager import get_async_session
from src.game.game_algorithm import PowerUpType
from src.game.game_events import GameEvent, PowerUpUsageResult
from src.game.game_manager import GameError, GameManager, GetGameManager
from src.game.websocket_manager import WebSocketManager, get_websocket_manager
from src.core.dependencies import get_current_user

logger = logging.getLogger(__name__)

game_router = APIRouter(prefix="/game", tags=[APITags.GAMES])


# ── Request Models ───────────────────────────────────────────────────────────


class StartGameRequest(BaseModel):
    secret_words: List[str] = Field(..., min_length=1, description="List of secret words for each round")
    max_attempts: int = Field(default=6, ge=1, le=10, description="Maximum guess attempts per word")


class JoinGameRequest(BaseModel):
    room_code: str = Field(..., description="4-digit room code to join")
    secret_words: List[str] = Field(..., min_length=1, description="List of secret words matching match total rounds")


class MakeGuessRequest(BaseModel):
    guess: str = Field(..., description="Word guess attempt")


class UsePowerUpRequest(BaseModel):
    powerup_type: PowerUpType = Field(..., description="Type of power-up to use")


# ── Helper Functions ─────────────────────────────────────────────────────────


async def generate_unique_room_code(game_repo: Repository[Game]) -> str:
    """Generate a unique 4-digit room code."""
    for _ in range(100):
        code = f"{random.randint(1000, 9999)}"
        existing = await game_repo.get(options=QueryOptions(filters={"room_code": code}))
        if not existing:
            return code
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Failed to generate unique room code",
    )


async def cancel_user_waiting_games(
    user_ids: List[str],
    session: AsyncSession,
    current_game_id: Optional[str] = None,
):
    """
    Cancel any other games in WAITING status where any of the specified user_ids
    is either player_1 or player_2 using a direct SQLAlchemy update query.
    """
    if not user_ids:
        return

    where_cond = (
        (col(Game.status) == GameStatus.WAITING) &
        (col(Game.player_1).in_(user_ids) | col(Game.player_2).in_(user_ids))
    )
    if current_game_id:
        where_cond = where_cond & (col(Game.id) != current_game_id)

    statement = (
        sqlalchemy_update(Game)
        .where(where_cond)
        .values(status=GameStatus.CANCELLED)
    )
    await session.exec(statement)
    await session.commit()


# ── Endpoints ────────────────────────────────────────────────────────────────


@game_router.post("/start", response_model=BaseResponse[Game], status_code=status.HTTP_201_CREATED)
async def start_game(
    request: StartGameRequest,
    user: User = Depends(get_current_user),
    game_repo: Repository[Game] = Depends(GetRepository(Game)),
    session: AsyncSession = Depends(get_async_session),
    user_repo: Repository[User] = Depends(GetRepository(User)),
    word_repo: Repository[Word] = Depends(GetRepository(Word)),
    ws_manager: WebSocketManager = Depends(get_websocket_manager),
):
    """
    Start a new game session as Player 1.
    Submits secret words and config, validates word lengths, generates a 4-digit room code,
    inserts the waiting Game record into DB, and cancels any other waiting games for the user.
    """
    if not request.secret_words:
        raise HTTPException(status_code=400, detail="secret_words list cannot be empty")

    words = [w.strip().upper() for w in request.secret_words if w.strip()]
    if not words:
        raise HTTPException(status_code=400, detail="Invalid secret words provided")

    word_length = len(words[0])
    if any(len(w) != word_length for w in words):
        raise HTTPException(status_code=400, detail="All secret words must have the exact same length")

    room_code = await generate_unique_room_code(game_repo)
    total_rounds = len(words)

    game = Game(
        room_code=room_code,
        status=GameStatus.WAITING,
        current_turn=Player.p1,
        player_1=user.id,
        player_1_words=words,
        total_rounds=total_rounds,
        max_attempts=request.max_attempts,
        word_length=word_length,
    )

    created_game = await game_repo.add(game)
    await cancel_user_waiting_games([user.id], session=session, current_game_id=created_game.id)

    return BaseResponse(
        message="Game created successfully. Share room code to let Player 2 join.",
        data=created_game
    )


@game_router.post("/join", response_model=BaseResponse[Game])
async def join_game(
    request: JoinGameRequest,
    user: User = Depends(get_current_user),
    game_repo: Repository[Game] = Depends(GetRepository(Game)),
    session: AsyncSession = Depends(get_async_session),
    user_repo: Repository[User] = Depends(GetRepository(User)),
    word_repo: Repository[Word] = Depends(GetRepository(Word)),
    ws_manager: WebSocketManager = Depends(get_websocket_manager),
):
    """
    Join an existing waiting game session as Player 2 using a 4-digit room code.
    Validates word count and lengths, sets status to IN_PROGRESS with Player 1's turn,
    cancels any other waiting games for either player, and updates DB.
    """
    game = await game_repo.get(options=QueryOptions(filters={"room_code": request.room_code.strip()}))
    if not game or game.status != GameStatus.WAITING:
        raise HTTPException(status_code=404, detail="Game not found or not waiting for players")

    if game.player_1 == user.id:
        raise HTTPException(status_code=400, detail="Player 1 cannot join their own game as Player 2")

    words = [w.strip().upper() for w in request.secret_words if w.strip()]
    if len(words) != game.total_rounds:
        raise HTTPException(
            status_code=400,
            detail=f"Must provide exactly {game.total_rounds} secret words for this match",
        )

    if any(len(w) != game.word_length for w in words):
        raise HTTPException(
            status_code=400,
            detail=f"All secret words must be exactly {game.word_length} letters long",
        )

    game.player_2 = user.id
    game.player_2_words = words
    game.status = GameStatus.IN_PROGRESS
    game.current_turn = Player.p1

    updated_game = await game_repo.update(game)
    await cancel_user_waiting_games([game.player_1, user.id], session=session, current_game_id=game.id)

    return BaseResponse(
        message="Joined game successfully. Game is now in progress.",
        data=updated_game
    )


@game_router.get("/current", response_model=BaseResponse[Game])
async def get_current_game(
    user: User = Depends(get_current_user),
    game_repo: Repository[Game] = Depends(GetRepository(Game)),
):
    """
    Fetch the currently active (in progress) game for the authenticated user
    where they are either Player 1 or Player 2.
    """
    where_cond = (
        (col(Game.status) == GameStatus.IN_PROGRESS) &
        ((col(Game.player_1) == user.id) | (col(Game.player_2) == user.id))
    )
    game = await game_repo.get(options=QueryOptions(where=[where_cond]))
    if not game:
        raise HTTPException(status_code=404, detail="No in-progress game found for current user")

    return BaseResponse(message="Current game retrieved successfully", data=game)


@game_router.get("/room/{room_code}", response_model=BaseResponse[Game])
async def get_game_by_room_code(
    room_code: str,
    game_repo: Repository[Game] = Depends(GetRepository(Game)),
):
    """
    Fetch game details by 4-digit room code.
    """
    game = await game_repo.get(options=QueryOptions(filters={"room_code": room_code.strip()}))
    if not game:
        raise HTTPException(status_code=404, detail="Game not found for room code")

    return BaseResponse(message="Game details retrieved", data=game)


@game_router.get("/{game_id}", response_model=BaseResponse[Game])
async def get_game_by_id(
    game_id: str,
    game_repo: Repository[Game] = Depends(GetRepository(Game)),
):
    """
    Fetch game details by game ID.
    """
    game = await game_repo.get(id=game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Game not found for given ID")

    return BaseResponse(message="Game details retrieved", data=game)


@game_router.post("/guess/{game_id}", response_model=BaseResponse[GameEvent])
async def make_guess(
    game_id: str,
    request: MakeGuessRequest,
    user: User = Depends(get_current_user),
    game_manager: GameManager = Depends(GetGameManager()),
):
    """Make a word guess in an active game."""
    try:
        event = await game_manager.make_guess(user.id, request.guess.strip())
        return BaseResponse(message="Guess processed", data=event)
    except GameError as e:
        raise HTTPException(status_code=400, detail=str(e))


@game_router.post("/powerup/{game_id}", response_model=BaseResponse[PowerUpUsageResult])
async def use_powerup(
    game_id: str,
    request: UsePowerUpRequest,
    user: User = Depends(get_current_user),
    game_manager: GameManager = Depends(GetGameManager()),
):
    """Use a power-up during a turn."""
    try:
        result = await game_manager.use_powerup(user.id, request.powerup_type)
        return BaseResponse(message="Power-up used successfully", data=result)
    except GameError as e:
        raise HTTPException(status_code=400, detail=str(e))


@game_router.post("/pause/{game_id}", response_model=BaseResponse[GameEvent])
async def pause_game(
    game_id: str,
    user: User = Depends(get_current_user),
    game_manager: GameManager = Depends(GetGameManager()),
):
    """Pause an in-progress game."""
    try:
        event = await game_manager.pause_game(user.id)
        return BaseResponse(message="Game paused successfully", data=event)
    except GameError as e:
        raise HTTPException(status_code=400, detail=str(e))


@game_router.post("/resume/{game_id}", response_model=BaseResponse[GameEvent])
async def resume_game(
    game_id: str,
    user: User = Depends(get_current_user),
    game_manager: GameManager = Depends(GetGameManager()),
):
    """Resume a paused game."""
    try:
        event = await game_manager.resume_game(user.id)
        return BaseResponse(message="Game resumed successfully", data=event)
    except GameError as e:
        raise HTTPException(status_code=400, detail=str(e))


@game_router.post("/quit/{game_id}", response_model=BaseResponse[GameEvent])
async def quit_game(
    game_id: str,
    user: User = Depends(get_current_user),
    game_manager: GameManager = Depends(GetGameManager()),
):
    """Quit / forfeit an ongoing game."""
    try:
        event = await game_manager.end_game(reason=f"Player {user.username or user.id} quit the game")
        return BaseResponse(message="Game quit successfully", data=event)
    except GameError as e:
        raise HTTPException(status_code=400, detail=str(e))


@game_router.post("/switch-turn/{game_id}", response_model=BaseResponse[GameEvent])
@game_router.post("/switch_turn/{game_id}", response_model=BaseResponse[GameEvent], include_in_schema=False)
async def switch_turn(
    game_id: str,
    user: User = Depends(get_current_user),
    game_manager: GameManager = Depends(GetGameManager()),
):
    """
    Switch player turn when the turn timer on the client hits zero.
    If switching turn in the last round and the last active player was player 2,
    the game is finalized as Game Over.
    """
    try:
        event = await game_manager.switch_player_turn(player_id=user.id)
        return BaseResponse(message="Turn switched successfully", data=event)
    except (GameError, AssertionError) as e:
        raise HTTPException(status_code=400, detail=str(e))


# ── WebSocket Updates Endpoint ────────────────────────────────────────────────


@game_router.websocket("/ws")
@game_router.websocket("/updates")
async def game_updates_websocket(
    websocket: WebSocket,
    user_id: str = Query(..., description="User ID of the connecting player"),
    ws_manager: WebSocketManager = Depends(get_websocket_manager),
):
    """
    WebSocket endpoint for receiving game updates broadcasted via WebSocketManager.
    Connects the user via their user_id query parameter and maintains the connection.
    """
    connected = await ws_manager.connect(websocket, user_id=user_id)
    if not connected:
        return

    try:
        while True:
            # Hold the connection open and listen for client messages / pings
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info(f"WebSocket client disconnected for user_id: {user_id}")
    except Exception as e:
        logger.warning(f"WebSocket connection error for user_id {user_id}: {e}")
    finally:
        await ws_manager.disconnect(user_id=user_id, reason="Connection closed")


