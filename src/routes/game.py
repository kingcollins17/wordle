# In your router or controller

from typing import Annotated
from fastapi import (
    WebSocket,
    WebSocketDisconnect,
    Depends,
    APIRouter,
    Query,
    HTTPException,
    WebSocketException,
)
from src.core.ai_service import AiService, get_ai_service
from src.core.api_tags import APITags
from src.core.base_response import BaseResponse
from src.core.config import Config
from src.game.game_reward_manager import GameReward, get_game_reward_manager
from src.core.models.user import User
from src.core.models.game import Game
from src.core.repository import Repository, GetRepository
from src.routes.auth import get_current_user
from src.database import *
from src.game import *

game_router = APIRouter(prefix="/game", tags=[APITags.GAMES])


@game_router.get("")
async def get_game_session(
    session_id: str,
    game_manager: GameManager = Depends(get_game_manager),
) -> BaseResponse[GameSession]:
    try:
        game = await game_manager.get_game_session(session_id)
        if not game:
            raise HTTPException(status_code=404, detail="Game not found")
        return BaseResponse(data=game, message="Game found")
    except Exception as e:
        logger.error(f"Error testing ai service {e}, {type(e)}")
        raise HTTPException(status_code=500, detail=f"{e}")


@game_router.websocket("/ws/game/{game_id}")
async def game(
    game_id: str,
    websocket: WebSocket,
    player_id: str = Query(...),
    ws_manager: WebSocketManager = Depends(get_websocket_manager),
    game_manager: GameManager = Depends(get_game_manager),
    user_repo: Repository[User] = Depends(GetRepository(User)),
):
    """
    Simplified game WebSocket handler.
    - Connects the user to the WebSocket
    - Sends the current game state
    - Handles gameplay loop for in_progress games
    - Users signal readiness via REST endpoints
    """
    user = await user_repo.get(id=player_id)
    await ws_manager.connect(websocket=websocket, device_id=player_id, user=user)

    try:
        if not user:
            raise GameError("User not found")

        game = await game_manager.get_game_session(game_id)
        if not game:
            raise GameError("Game not found")

        if player_id not in game.players:
            raise GameError("Player not in game")

        # Handle game over state
        if game.game_state == GameState.game_over:
            await ws_manager.disconnect(player_id, reason="Game Over")
            return

        # broadcast game update before listening to socket
        # Send current game state to the connecting player

        await game_manager.broadcast_game_state(game_id)
        # Keep WebSocket connection open and listen for messages
        # Connection stays open for all game states (waiting, paused, in_progress)
        try:
            while True:
                game = await game_manager.get_game_session(game_id)
                
                # Disconnect if game is over or doesn't exist
                if not game or game.game_state == GameState.game_over:
                    break
                
                # Wait for player input
                data = await websocket.receive_text()
                stripped = data.strip()

                # Only process guesses if game is in progress
                if game.game_state == GameState.in_progress:
                    await game_manager.play(
                        session_id=game_id,
                        player_id=player_id,
                        guess=stripped,
                    )
                    
                    # Refresh connection to keep it alive
                    await ws_manager.refresh_connection(websocket, player_id)

                    # If playing against bot, handle bot turn
                    opponent_id = next(pid for pid in game.players if pid != player_id)

                    if opponent_id.startswith("bot_"):
                        bot = bot_manager.active_bots.get(opponent_id)

                        if bot:
                            # Wait between 2 and 10 seconds
                            wait_time = random.randint(2, 10)
                            await asyncio.sleep(wait_time)

                            guess = await bot.play(game_manager)
                            await game_manager.play(
                                session_id=game.session_id,
                                player_id=opponent_id,
                                guess=guess,
                            )
                else:
                    # Game is waiting or paused - send info message
                    await ws_manager.send_to_device(
                        player_id,
                        message=WebSocketMessage(
                            type=MessageType.INFO,
                            data=InfoPayload(
                                message=f"Game is {game.game_state}. Please wait for the game to start or resume."
                            ),
                        ),
                    )

        except WebSocketDisconnect:
            pass
        
        await ws_manager.disconnect(player_id, reason="Connection closed")
        
    except GameError as er:
        logger.error(f"Error playing game: {er}")
        await ws_manager.disconnect(player_id, reason=f"{er}")
    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.error(f"Error playing game: {e}")
        await ws_manager.disconnect(player_id, reason=f"{e}")


@game_router.websocket("/ws/matchmaking")
async def matchmaking_ws(
    websocket: WebSocket,
    player_id: str,
    secret_word: str = Query(...),
    queue: MatchmakingQueue = Depends(get_matchmaking_queue),
    game_manager: GameManager = Depends(get_game_manager),
    ws_manager: WebSocketManager = Depends(get_websocket_manager),
    user_repo: Repository[User] = Depends(GetRepository(User)),
    games_repo: Repository[Game] = Depends(GetRepository(Game)),
):
    await ws_manager.connect(websocket=websocket, device_id=player_id)
    user = await user_repo.get(id=player_id)

    if not user:
        await ws_manager.disconnect(player_id, reason="User not found in database")
        return

    await queue.add_player(
        player_id,
        websocket,
        secret_word=secret_word,
    )
    player1_user: Optional[User] = None
    player2_user: Optional[User] = None
    player1_secret: Optional[str] = None
    player2_secret: Optional[str] = None
    try:
        matched = await queue.wait_for_match(
            player_id, timeout=Config.WAITING_ROOM_TIMEOUT
        )
        assert (
            matched is None or matched.player1 != matched.player2
        ), "Player cannot be matched with self"

        if matched:
            player1_user = await user_repo.get(id=matched.player1)
            player1_secret = queue.secret_words.get(matched.player1)
            player2_user = await user_repo.get(id=matched.player2)
            player2_secret = queue.secret_words.get(matched.player2)

        game = await game_manager.get_player_game_session(player_id)

        if not game and player1_user and player2_user:
            game = await game_manager.create_game(
                player1_user=player1_user,
                player2_user=player2_user,
                player1_secret_words=[player1_secret],
                player2_secret_words=[player2_secret],
                settings=GameSettings(
                    rounds=1,
                    word_length=len(secret_word),
                    versusAi=False,
                    turn_time_limit=Config.DEFAULT_TURN_TIME_LIMIT,
                ),
            )
            game_manager.register_after_game_handler(
                game.session_id,
                PowerUpPersistenceAfterGameHandler(user_repo),
            )
            game_manager.register_after_game_handler(
                game.session_id,
                IncrementGamesPlayedAfterGameHandler(
                    repository=games_repo,
                    user_repository=user_repo,
                ),
            )

        if game:
            await ws_manager.send_to_device(
                device_id=player_id,
                message=WebSocketMessage(type=MessageType.MATCHED, data=game),
            )

        await queue.remove_player(player_id)
        await ws_manager.disconnect(
            player_id,
            reason="Matchmaking complete",
        )

    except WebSocketDisconnect:
        await queue.remove_player(player_id)
    except Exception as e:
        logger.error(f"Error in matchmaking: {e}")
        await ws_manager.disconnect(player_id, reason="Internal matchmaking error")


@game_router.get("/current-session", response_model=BaseResponse[Optional[GameSession]])
async def get_current_game_session(
    user: WordleUser = Depends(get_current_user),
    game_manager: GameManager = Depends(get_game_manager),
) -> BaseResponse[Optional[GameSession]]:
    """
    Get the current active game session for the authenticated user.
    Returns None if the user has no active game.
    """
    try:
        game = await game_manager.get_player_game_session(user.device_id)
        if not game:
            return BaseResponse(message="No active game session found", data=None)
        return BaseResponse(message="Active game session found", data=game)
    except Exception as e:
        logger.error(
            f"Error fetching current game session for user {user.device_id}: {e}"
        )
        raise HTTPException(status_code=500, detail="Internal server error")


@game_router.post("/end/{game_id}", response_model=BaseResponse[bool])
async def end_game(
    game_id: str,
    user: WordleUser = Depends(get_current_user),
    game_manager: GameManager = Depends(get_game_manager),
) -> BaseResponse[bool]:
    try:
        # Get the game session
        game_session = await game_manager.get_game_session(game_id)
        if not game_session:
            raise HTTPException(status_code=404, detail="Game not found")

        # Ensure user is part of the game
        if user.device_id not in game_session.players:
            raise HTTPException(status_code=403, detail="You are not part of this game")

        # Find opponent (they should be the winner)
        opponent = game_session.get_opponent(user.device_id)
        if not opponent:
            raise HTTPException(status_code=404, detail="Opponent not found")

        # Notify opponent before ending the game
        try:
            await game_manager.websocket_manager.send_to_device(
                device_id=opponent.player_id,
                message=WebSocketMessage(
                    type=MessageType.INFO,
                    data=InfoPayload(message=f"{user.username} has ended the game"),
                ),
            )
        except Exception as e:
            logger.error(f"Failed to notify opponent before ending game: {e}")

        # End the game with opponent as winner
        success = await game_manager.end_game(
            game_id,
            winner_id=opponent.player_id,
            reason=f"{user.username} ended the game",
        )

        return BaseResponse(message="Game ended successfully", data=success)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error ending game: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@game_router.post("/pause/{game_id}", response_model=BaseResponse[bool])
async def pause_game(
    game_id: str,
    user: WordleUser = Depends(get_current_user),
    game_manager: GameManager = Depends(get_game_manager),
) -> BaseResponse[bool]:
    """
    Pause an active game session.
    Only games in 'in_progress' state can be paused.
    """
    try:
        # Get the game session
        game_session = await game_manager.get_game_session(game_id)
        if not game_session:
            raise HTTPException(status_code=404, detail="Game not found")

        # Ensure user is part of the game
        if user.device_id not in game_session.players:
            raise HTTPException(status_code=403, detail="You are not part of this game")

        # Pause the game
        success = await game_manager.pause_game(game_id, user.device_id)

        return BaseResponse(message="Game paused successfully", data=success)

    except GameError as e:
        logger.error(f"GameError pausing game: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error pausing game: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@game_router.post("/resume/{game_id}", response_model=BaseResponse[bool])
async def resume_game(
    game_id: str,
    user: WordleUser = Depends(get_current_user),
    game_manager: GameManager = Depends(get_game_manager),
) -> BaseResponse[bool]:
    """
    Request to resume a paused game session.
    Uses a voting system - all players must vote to resume before the game continues.
    Returns True if the game was resumed (all players voted), False if still waiting for votes.
    """
    try:
        # Get the game session
        game_session = await game_manager.get_game_session(game_id)
        if not game_session:
            raise HTTPException(status_code=404, detail="Game not found")

        # Ensure user is part of the game
        if user.device_id not in game_session.players:
            raise HTTPException(status_code=403, detail="You are not part of this game")

        # Request to resume the game
        resumed = await game_manager.resume_game(game_id, user.device_id)

        if resumed:
            return BaseResponse(
                message="Game resumed successfully - all players ready", data=True
            )
        else:
            return BaseResponse(
                message="Resume vote registered - waiting for other players", data=False
            )

    except GameError as e:
        logger.error(f"GameError resuming game: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error resuming game: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# REST API
class LobbyInfo(BaseModel):
    lobby_code: str
    host_id: str
    player_ids: List[str]
    num_players: int
    is_full: bool
    has_settings: bool
    settings: Optional[dict] = None



class LobbyCodeResponse(BaseModel):
    lobby_code: str


@game_router.get("/generate-code", response_model=BaseResponse[LobbyCodeResponse])
async def generate_lobby_code(
    lobby_manager: LobbyManager = Depends(lobby_manager),
):
    """
    Generate a new unique lobby code.

    Returns:
        BaseResponse containing the newly generated lobby code
    """
    lobby_code = lobby_manager.generate_code()

    return BaseResponse[LobbyCodeResponse](
        data=LobbyCodeResponse(lobby_code=lobby_code),
        message="Lobby code generated successfully",
    )


class UsePowerUpRequest(BaseModel):
    player_id: str
    power_up_type: PowerUpType
    already_revealed_indices: Optional[List[int]] = None
    already_fished_letters: Optional[List[str]] = None


@game_router.post("/power-up/use", response_model=BaseResponse[PowerUpResult])
async def use_power_up(
    request: UsePowerUpRequest,
    game_manager: Annotated[GameManager, Depends(get_game_manager)],
):
    try:
        result = await game_manager.use_power_up(
            player_id=request.player_id,
            power_up_type=request.power_up_type,
            already_revealed_indices=request.already_revealed_indices,
            already_fished_letters=request.already_fished_letters,
        )

        response = PowerUpResult(
            type=request.power_up_type,
            fished_letter=(
                result if request.power_up_type == PowerUpType.FISH_OUT else None
            ),
            revealed_letter=(
                RevealedLetter(
                    letter=result[0],
                    index=result[1],
                )
                if request.power_up_type == PowerUpType.REVEAL_LETTER
                else None
            ),
            word_meaning=(
                result if request.power_up_type == PowerUpType.WORD_MEANING else None
            ),
        )
        return BaseResponse[PowerUpResult](
            message="Power-up used successfully",
            data=response,
        )

    except GameError as e:
        logger.error(f"Error using power-up: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        import traceback

        traceback.print_exc()
        logger.error(f"Unexpected error using power-up: {e}")

        raise HTTPException(status_code=500, detail="Unexpected error occurred")


class PowerUpAdjustmentRequest(BaseModel):
    player_id: str = Field(..., description="Player's device ID")
    power_up_type: PowerUpType = Field(..., description="Type of power-up to modify")
    amount: int = Field(default=1, ge=1, description="Amount to increment or decrement")


@game_router.post("/power-up/increment", response_model=BaseResponse[int])
async def increment_power_up(
    request: PowerUpAdjustmentRequest,
    game_manager: Annotated[GameManager, Depends(get_game_manager)],
):
    """
    Increment a player's specific power-up count in game
    """
    try:
        new_count = await game_manager.increment_power_up(
            player_id=request.player_id,
            power_up_type=request.power_up_type,
            amount=request.amount,
        )
        return BaseResponse[int](
            message=f"{request.power_up_type.value} incremented successfully",
            data=new_count,
        )
    except GameError as e:
        logger.error(f"GameError incrementing power-up: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error incrementing power-up: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@game_router.post("/power-up/decrement", response_model=BaseResponse[int])
async def decrement_power_up(
    request: PowerUpAdjustmentRequest,
    game_manager: Annotated[GameManager, Depends(get_game_manager)],
):
    """
    Decrement a player's specific power-up count in game
    """
    try:
        new_count = await game_manager.decrement_power_up(
            player_id=request.player_id,
            power_up_type=request.power_up_type,
            amount=request.amount,
        )
        return BaseResponse[int](
            message=f"{request.power_up_type.value} decremented successfully",
            data=new_count,
        )
    except GameError as e:
        logger.error(f"GameError decrementing power-up: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error decrementing power-up: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


class RewardType(str, Enum):
    COINS = "coins"
    REVEAL_LETTER = "reveal_letter"
    FISH_OUT = "fish_out"
    WORD_MEANING = "word_meaning"


class RewardUserRequest(BaseModel):
    device_id: str = Field(..., description="User's device ID")
    reward_type: RewardType = Field(..., description="Type of reward to give")
    amount: int = Field(1, ge=1, description="Amount to increment")


@game_router.get("/rewards/{game_id}")
async def get_game_rewards(
    attempts: int,
    won: bool,
    reward_manager: GameRewardManager = Depends(get_game_reward_manager),
    user: WordleUser = Depends(get_current_user),
) -> BaseResponse[GameReward]:
    try:
        rewards = await reward_manager.generate_reward(
            user=user, won=won, attempts=attempts
        )
        return BaseResponse(message="Got Rewards", data=rewards)
    except Exception as e:
        logger.error(f"Error rewarding user: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@game_router.post("/rewards/{game_id}")
async def claim_game_rewards(
    data: GameReward,
    reward_manager: GameRewardManager = Depends(get_game_reward_manager),
    user: WordleUser = Depends(get_current_user),
) -> BaseResponse[WordleUser]:
    try:
        updated_user = await reward_manager.claim_reward(user, data)
        return BaseResponse(message="Rewards claimed", data=updated_user)
    except Exception as e:
        logger.error(f"Error getting rewards: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


@game_router.post("/reward-user", response_model=BaseResponse[User])
async def reward_user(
    request: RewardUserRequest,
    user_repo: Repository[User] = Depends(GetRepository(User)),
):
    try:
        user = await user_repo.get(id=request.device_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        update_field = request.reward_type.value
        current_val = getattr(user, update_field, 0)
        updated_user = await user_repo.update(user, {update_field: current_val + request.amount})

        return BaseResponse(
            message="User rewarded successfully", data=updated_user
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error rewarding user: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
