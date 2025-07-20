# In your router or controller

from fastapi import (
    WebSocket,
    WebSocketDisconnect,
    Depends,
    APIRouter,
    Query,
    HTTPException,
    WebSocketException,
)
from src.core.api_tags import APITags
from src.core.config import Config
from src.repositories import UserRepository
from src.database import *
from src.game import *

game_router = APIRouter(prefix="/game", tags=[APITags.GAMES])


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

        try:
            is_reconnecting = True
            if game.game_state == GameState.game_over:
                ws_manager.disconnect(player_id, reason="Game Over")
                return
            if game.game_state == GameState.waiting:
                is_reconnecting = False
                lobby = lobby_manager.get_lobby(game_id)
                if not lobby:
                    lobby = lobby_manager.create_lobby(game_id)

                lobby.add_player(
                    player_id,
                    websocket,
                )
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
                    await ws_manager.disconnect(player_id, "Waiting Lobby timed out")
                    return
            if is_reconnecting:
                await ws_manager.send_to_device(
                    player_id,
                    message=WebSocketMessage(
                        type=MessageType.GAME_STATE,
                        data=await game_manager.get_game_session(game_id),
                    ),
                )
            while True:
                game = await game_manager.get_game_session(game_id)

                if not game or game.game_state != GameState.in_progress:
                    break
                # ensure text is a word guess that matches the word length in game settings
                data = await websocket.receive_text()
                stripped = data.replace("\n", "").replace("\t", "").replace("\r", "")
                print(f"stripped = {stripped}")

                await game_manager.play(
                    session_id=game_id,
                    player_id=player_id,
                    guess=stripped,
                )

                # if playing against bot, check if turn it is bots turn and handle bot game play here
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
    queue: MatchmakingQueue = Depends(get_matchmaking_queue),
):
    await websocket.accept()
    await queue.add_player(player_id, websocket)

    try:
        while True:
            data = await websocket.receive_text()
            # optionally handle pings or keepalives
    except WebSocketDisconnect:
        # optionally remove player from queue
        pass


@game_router.websocket("/ws/lobby/{lobby_code}")
async def lobby_ws(
    websocket: WebSocket,
    lobby_code: str,
    player_id: str = Query(...),
    secret_word: str = Query(...),
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

        lobby = lobby_manager.get_lobby(lobby_code)
        if not lobby:
            lobby = lobby_manager.create_lobby(lobby_code)

        lobby.add_player(
            player_id,
            websocket,
            secret_word=secret_word,
        )

        try:
            await asyncio.wait_for(lobby.ready.wait(), timeout=Config.LOBBY_TIMEOUT)
        except asyncio.TimeoutError:
            await ws_manager.disconnect(player_id, "Lobby timed out")
            return

        players = list(lobby.players.keys())
        secret_words = lobby.secret_words
        if len(secret_words.keys()) != 2:
            raise GameError("secret words must 2 to start a game")
        game = await game_manager.get_player_game_session(player_id)
        if not game:
            game = await game_manager.create_game(
                player1_user=WordleUser(**await repo.get_user_by_device_id(players[0])),
                player2_user=WordleUser(**await repo.get_user_by_device_id(players[1])),
                player1_secret_word=secret_words[players[0]],
                player2_secret_word=secret_words[players[1]],
            )
        await ws_manager.send_to_device(
            player_id,
            message=WebSocketMessage(
                type=MessageType.MATCHED,
                data=game,
            ),
        )

        await ws_manager.disconnect(player_id, reason="You have been matched")
        lobby_manager.remove_lobby(lobby_code)
    except Exception as e:
        logger.error(f"Error connecting to Lobby {e}")

        await ws_manager.disconnect(player_id, reason="Something went wrong")
