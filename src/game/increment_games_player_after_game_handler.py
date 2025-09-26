from datetime import datetime
from typing import Optional, Union
from src.models.game_session import AfterGameHandler, GameSession, GameState, PlayerRole
from src.models.wordle_user import WordleUser
from src.repositories.games_repository import GamesRepository
from src.repositories.user_repository import UserRepository


class IncrementGamesPlayedAfterGameHandler(AfterGameHandler):
    """
    Persists remaining power-up counts (fish_out, reveal_letter, ai_meaning)
    to the database for each player after the game ends.
    """

    def __init__(self, repository: GamesRepository, user_repository: UserRepository):
        super().__init__()
        self.repository = repository
        self.user_repository = user_repository

    async def handle(self, game: GameSession) -> None:
        if game.game_state != GameState.game_over:
            return  # Only persist after game over

        try:
            # Build records for both players
            games_data = []
            completed_at = (
                game.outcome.completed_at if game.outcome else datetime.utcnow()
            )
            keys = game.players.keys()
            values = list(game.players.values())

            assert len(keys) == 2, "Only two players allowed"
            assert len(values) == 2, "Only two players allowed"
            p1_info = game.get_player_by_role(PlayerRole.player1)
            p2_info = game.get_player_by_role(PlayerRole.player1)

            p1 = await self.user_repository.get_user_by_device_id(keys[0])
            p2 = await self.user_repository.get_user_by_device_id(keys[1])

            p2 = WordleUser(**p2) if p2 else None
            if p1:
                winner_id: Optional[int] = None
                p1 = WordleUser(**p1)

                if not game.outcome or not game.outcome.winner_id:
                    winner_id = None
                elif game.outcome.winner_id == p1.device_id:
                    winner_id = p1.id
                elif p2 and game.outcome.winner_id == p2.device_id:
                    winner_id = p2.id
                else:
                    winner_id = None

                # id	bigint unsigned	NO	PRI	NULL	auto_increment
                # p1_id	int unsigned	NO	MUL	NULL
                # p2_id	int unsigned	NO	MUL	NULL
                # p1_username	varchar(255)	NO		NULL
                # p2_username	varchar(255)	NO		NULL
                # p1_device_id	varchar(255)	NO		NULL
                # p2_device_id	varchar(255)	NO		NULL
                # p1_secret_words	json	NO		NULL
                # p2_secret_words	json	NO		NULL
                # winner_id	int unsigned	YES	MUL	NULL
                # rounds	int unsigned	NO		1
                # completed_at	timestamp	NO		CURRENT_TIMESTAMP	DEFAULT_GENERATED
                games_data.append(
                    {
                        "p1_id": p1.id,
                        "p2_id": p2.id if p2 else 0,
                        "p1_username": p1.username,
                        "p2_username": (
                            p2.username if p2 else p2_info.username or "Unknown Player"
                        ),
                        "p1_device_id": p1.device_id,
                        "p2_device_id": p2.device_id if p2 else p2_info.player_id,
                        "p1_secret_words": p1_info.secret_words,
                        "p2_secret_words": p2_info.secret_words,
                        "word_length": game.settings.word_length,
                        "rounds": len(p1_info.secret_words),
                        # "completed_at": completed_at,
                        "winner_id": winner_id or 0,
                    }
                )

            # Insert both player records in one call
            await self.repository.create_many_games(games_data)

        except Exception as e:
            import logging

            logger = logging.getLogger(__name__)
            logger.error(f"Error inserting games after session {game.session_id}: {e}")
            raise
