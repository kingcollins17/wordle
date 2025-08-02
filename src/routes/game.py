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
from src.repositories import UserRepository, get_user_repository
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
    lobby_manager: LobbyManager = Depends(lobby_manager),
    ws_manager: WebSocketManager = Depends(get_websocket_manager),
    redis_: RedisService = Depends(get_redis),
    mysql: MySQLConnectionManager = Depends(get_mysql_manager),
    game_manager: GameManager = Depends(get_game_manager),
    bot_manager: BotManager = Depends(get_bot_manager),
):
    repo = UserRepository(mysql, redis_)
    user_data = await repo.get_user_by_device_id(device_id=player_id)
    user = WordleUser(**user_data) if user_data else None
    await ws_manager.connect(websocket=websocket, device_id=player_id, user=user)

    try:
        if not user:
            raise GameError("User not found")

        game = await game_manager.get_game_session(game_id)
        if not game:
            raise GameError("Game not found")
        assert player_id in list(game.players.keys()), "Player not in game"
        try:
            is_reconnecting = True

            if game.game_state == GameState.game_over:
                await ws_manager.disconnect(player_id, reason="Game Over")
                return

            if game.game_state == GameState.waiting:
                is_reconnecting = False
                lobby = lobby_manager.get_lobby(game_id)
                if not lobby:
                    lobby = lobby_manager.create_lobby(game_id)
                await ws_manager.send_to_device(
                    player_id,
                    message=WebSocketMessage(
                        type=MessageType.WAITING,
                        data=WaitingPayload(
                            waiting_for=next(
                                game.players[k]
                                for k in game.players.keys()
                                if k != player_id
                            ).username,
                        ),
                    ),
                )
                lobby.add_player(player_id, websocket)

                # 🧠 BOT AWARE START
                player_ids = list(game.players.keys())
                opponent_id = [pid for pid in player_ids if pid != player_id][0]

                if opponent_id.startswith("bot_"):
                    # bot is second player, start immediately
                    await bot_manager.reconnect_bot(
                        opponent_id,
                        game_id,
                        game_manager,
                        word_length=game.settings.word_length,
                    )
                    await game_manager.start_game(game_id)
                    game = await game_manager.get_game_session(game_id)
                else:
                    try:
                        # wait for second player to join game socket
                        await asyncio.wait_for(
                            lobby.ready.wait(),
                            timeout=Config.LOBBY_TIMEOUT,
                        )
                        game = await game_manager.get_game_session(game_id)

                        if game.game_state != GameState.in_progress:
                            await game_manager.start_game(game_id)
                    except asyncio.TimeoutError:
                        await ws_manager.disconnect(
                            player_id, "Waiting Lobby timed out"
                        )
                        return

            if is_reconnecting:
                await ws_manager.send_to_device(
                    player_id,
                    message=WebSocketMessage(
                        type=MessageType.GAME_STATE,
                        data=await game_manager.get_game_session(game_id),
                    ),
                )

            # Gameplay loop
            while True:
                game = await game_manager.get_game_session(game_id)
                if not game or game.game_state != GameState.in_progress:
                    break
                data = await websocket.receive_text()
                stripped = data.strip()

                await game_manager.play(
                    session_id=game_id,
                    player_id=player_id,
                    guess=stripped,
                )
                # Refresh connection to keep it alive
                # refresh connection mapping incase of accidental clean up
                await ws_manager.refresh_connection(websocket, player_id)

                # If playing against bot, handle bot turn
                opponent_id = next(pid for pid in game.players if pid != player_id)

                if opponent_id.startswith("bot_"):
                    bot = bot_manager.active_bots.get(opponent_id)

                    if bot:
                        guess = await bot.play(game_manager)
                        await game_manager.play(
                            session_id=game.session_id,
                            player_id=opponent_id,
                            guess=guess,
                        )

        except WebSocketDisconnect:
            pass
        await ws_manager.disconnect(player_id, reason="Nothing to do")
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
    redis_: RedisService = Depends(get_redis),
    mysql: MySQLConnectionManager = Depends(get_mysql_manager),
    bot_manager: BotManager = Depends(get_bot_manager),
):
    await ws_manager.connect(websocket=websocket, device_id=player_id)
    user_repo = UserRepository(mysql, redis_)
    user_data = await user_repo.get_user_by_device_id(player_id)

    if not user_data:
        await ws_manager.disconnect(player_id, reason="User not found in database")
        return

    await queue.add_player(
        player_id,
        websocket,
        secret_word=secret_word,
    )
    player1_user: Optional[WordleUser] = None
    player2_user: Optional[WordleUser] = None
    player1_secret: Optional[str] = None
    player2_secret: Optional[str] = None
    try:
        matched = await queue.wait_for_match(
            player_id, timeout=Config.WAITING_ROOM_TIMEOUT
        )
        assert (
            matched is None or matched.player1 != matched.player2
        ), "Player cannot be matched with self"
        current_user = WordleUser(**user_data)

        if matched is None:
            # No match, assign bot as opponent
            bot = bot_manager.create_bot(
                difficulty="medium",
                word_length=len(secret_word),
                opponents_word=secret_word,
            )

            # Connect bot's virtual websocket
            await ws_manager.connect(
                bot.virtual_ws,
                device_id=bot.bot_id,
                user=bot.user,
            )
            player1_user = current_user
            player1_secret = secret_word
            player2_user = bot.user
            player2_secret = bot.secret_word

        else:
            player1_user = WordleUser(
                **await user_repo.get_user_by_device_id(
                    matched.player1, bypass_cache=True
                )
            )
            player1_secret = queue.secret_words.get(matched.player1)
            # Matched with another player
            player2_user = WordleUser(
                **await user_repo.get_user_by_device_id(
                    matched.player2, bypass_cache=True
                )
            )
            player2_secret = queue.secret_words.get(matched.player2)

        game = await game_manager.get_player_game_session(player_id)

        if not game:
            # if theres a game means the first person in the room has created the game
            # Create game with player1 and
            game = await game_manager.create_game(
                player1_user=player1_user,
                player2_user=player2_user,
                player1_secret_words=[player1_secret],
                player2_secret_words=[player2_secret],
                settings=GameSettings(
                    rounds=1,
                    word_length=len(secret_word),
                    versusAi=True,
                    turn_time_limit=Config.DEFAULT_TURN_TIME_LIMIT,
                ),
            )
            scorer = ScoringAfterGameHandler(user_repo)
            game_manager.register_after_game_handler(game.session_id, scorer)
            game_manager.register_after_game_handler(
                game.session_id,
                PowerUpPersistenceAfterGameHandler(user_repo),
            )

        # If playing vs bot, set context and start bot game
        if matched is None:
            bot.set_game_context(game.session_id, secret_word)
            await bot.start_playing(game_manager, word_length=len(secret_word))

        # Notify player of match
        await ws_manager.send_to_device(
            device_id=player_id,
            message=WebSocketMessage(type=MessageType.MATCHED, data=game),
        )

        # Optional cleanup
        await queue.remove_player(player_id)
        await ws_manager.disconnect(
            player_id,
            reason=f"Matched with user {player2_user.username if player_id == player1_user.device_id else player1_user.username}",
        )

    except WebSocketDisconnect:
        await queue.remove_player(player_id)
    except Exception as e:
        logger.error(f"Error in matchmaking: {e}")
        import traceback

        traceback.print_exc()
        await ws_manager.disconnect(player_id, reason="Internal matchmaking error")


@game_router.websocket("/ws/lobby/{lobby_code}")
async def lobby_ws(
    websocket: WebSocket,
    lobby_code: str,
    player_id: str = Query(...),
    secret_word: List[str] = Query(...),
    rounds: int = Query(default=1),
    turn_time_limit: Optional[int] = Query(default=60, description="Turn time limit"),
    lobby_manager: LobbyManager = Depends(lobby_manager),
    ws_manager: WebSocketManager = Depends(get_websocket_manager),
    redis_: RedisService = Depends(get_redis),
    mysql: MySQLConnectionManager = Depends(get_mysql_manager),
    game_manager: GameManager = Depends(get_game_manager),
):
    repo = UserRepository(mysql, redis_)
    user_data = await repo.get_user_by_device_id(device_id=player_id)
    user = WordleUser(**user_data) if user_data else None

    await ws_manager.connect(websocket=websocket, device_id=player_id, user=user)

    try:
        if not user:
            await ws_manager.disconnect(player_id, "User not found")
            return

        # 🎮 Proceed to lobby
        lobby = lobby_manager.get_lobby(lobby_code)
        if not lobby:
            lobby = lobby_manager.create_lobby(lobby_code)
        if lobby.settings and len(secret_word) != lobby.settings.rounds:
            await ws_manager.disconnect(
                player_id,
                f"You must provide {lobby.settings.rounds} {lobby.settings.word_length} letter words",
            )
            return
        lobby.add_player(
            player_id,
            websocket,
            secret_words=secret_word,
        )
        if lobby.is_host(player_id):
            # ✅ Validate secret_word
            if len(secret_word) != rounds:
                await ws_manager.disconnect(
                    player_id, f"Expected {rounds} secret words, got {len(secret_word)}"
                )
                return

            word_lengths = [len(w) for w in secret_word]
            if len(set(word_lengths)) != 1:
                await ws_manager.disconnect(
                    player_id, "All secret words must be the same length"
                )
                return

            word_length = word_lengths[0]  # Safe since all are equal

            lobby.settings = GameSettings(
                rounds=rounds,
                word_length=word_length,
                turn_time_limit=turn_time_limit or Config.DEFAULT_TURN_TIME_LIMIT,
            )

        try:
            await asyncio.wait_for(lobby.ready.wait(), timeout=Config.LOBBY_TIMEOUT)
        except asyncio.TimeoutError:
            await ws_manager.disconnect(player_id, "Lobby timed out")
            return

        # ⛓️ Prevent race condition by locking game creation per lobby
        lobby_lock = lobby_manager.get_lock(lobby_code)
        async with lobby_lock:
            players = list(lobby.players.keys())

            if len(lobby.secret_words) != 2:
                raise GameError("Secret words not found")

            player1 = players[0]
            player2 = players[1]
            player1_secret_words = lobby.secret_words[player1]
            player2_secret_words = lobby.secret_words[player2]

            assert (
                len(player1_secret_words)
                == len(player2_secret_words)
                == lobby.settings.rounds
            ), f"Players 1 and 2 must each provide {lobby.settings.rounds} {lobby.settings.word_length} letter words"

            word_lengths = [len(w) for w in secret_word]
            if len(set(word_lengths)) != 1:
                await ws_manager.disconnect(
                    player_id, "All secret words must be the same length"
                )
                return
            assert (
                len(secret_word[0]) == lobby.settings.word_length
            ), f"Word must be a {lobby.settings.word_length} letter word"

            game = await game_manager.get_player_game_session(player_id)
            if not game:
                game = await game_manager.create_game(
                    player1_user=WordleUser(
                        **await repo.get_user_by_device_id(player1, bypass_cache=True)
                    ),
                    player2_user=WordleUser(
                        **await repo.get_user_by_device_id(player2, bypass_cache=True)
                    ),
                    player1_secret_words=player1_secret_words,
                    player2_secret_words=player2_secret_words,
                    settings=lobby.settings,
                )
                scorer = ScoringAfterGameHandler(repo)
                game_manager.register_after_game_handler(game.session_id, scorer)
                game_manager.register_after_game_handler(
                    game.session_id,
                    PowerUpPersistenceAfterGameHandler(repo),
                )

        await ws_manager.send_to_device(
            player_id,
            message=WebSocketMessage(
                type=MessageType.MATCHED,
                data=game,
            ),
        )
        lobby_manager.remove_lobby(lobby_code)
        await ws_manager.disconnect(player_id, reason="You have been matched")
    except Exception as e:
        logger.error(f"Error connecting to Lobby {e}")
        await ws_manager.disconnect(player_id, reason="Something went wrong")


# REST API
class LobbyInfo(BaseModel):
    lobby_code: str
    host_id: str
    player_ids: List[str]
    num_players: int
    is_full: bool
    has_settings: bool
    settings: Optional[dict] = None


@game_router.get("/lobby/{lobby_code}", response_model=BaseResponse[LobbyInfo])
async def get_lobby_info(
    lobby_code: str,
    lobby_manager: LobbyManager = Depends(lobby_manager),
):
    lobby = lobby_manager.get_lobby(lobby_code)
    if not lobby:
        raise HTTPException(status_code=404, detail="Lobby not found")

    info = LobbyInfo(
        lobby_code=lobby_code,
        host_id=lobby.host_id,
        player_ids=list(lobby.players.keys()),
        num_players=len(lobby.players),
        is_full=lobby.ready.is_set(),
        has_settings=lobby.settings is not None,
        settings=lobby.settings.dict() if lobby.settings else None,
    )

    return BaseResponse[LobbyInfo](data=info)


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
            ai_meaning=(
                result if request.power_up_type == PowerUpType.AI_MEANING else None
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
        logger.error(f"Unexpected error using power-up: {e}")
        raise HTTPException(status_code=500, detail="Unexpected error occurred")


@game_router.get("/test-ai")
async def use_power_up(
    word: str,
    ai_service: AiService = Depends(get_ai_service),
    # game_manager: Annotated[GameManager, Depends(get_game_manager)],
):
    try:
        result = await ai_service.get_word_definition(word)
        return result
    except Exception as e:
        logger.error(f"Error testing ai service {e}, {type(e)}")
        raise HTTPException(status_code=500, detail=f"{e}")


class RewardType(str, Enum):
    COINS = "coins"
    REVEAL_LETTER = "reveal_letter"
    FISH_OUT = "fish_out"
    AI_MEANING = "ai_meaning"


class RewardUserRequest(BaseModel):
    device_id: str = Field(..., description="User's device ID")
    reward_type: RewardType = Field(..., description="Type of reward to give")
    amount: int = Field(1, ge=1, description="Amount to increment")


@game_router.post("/reward-user", response_model=BaseResponse[WordleUser])
async def reward_user(
    request: RewardUserRequest,
    user_repo: Annotated[UserRepository, Depends(get_user_repository)],
):
    try:
        # Get the current user
        user = await user_repo.get_user_by_device_id(request.device_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Prepare the update based on reward type
        update_field = request.reward_type.value
        updates = {update_field: user[update_field] + request.amount}

        # Update the user
        await user_repo.update_user_by_device_id(request.device_id, updates)

        # Get the updated user to return
        updated_user = await user_repo.get_user_by_device_id(
            request.device_id, bypass_cache=True
        )
        return BaseResponse[WordleUser](
            message="User rewarded successfully", data=WordleUser(**updated_user)
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error rewarding user: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
