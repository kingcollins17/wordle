from src.models import GameSession, GameState, PowerUpType, AfterGameHandler
from src.repositories import UserRepository


class PowerUpPersistenceAfterGameHandler(AfterGameHandler):
    """
    Persists remaining power-up counts (fish_out, reveal_letter, ai_meaning)
    to the database for each player after the game ends.
    """

    def __init__(self, user_repository: UserRepository):
        super().__init__()
        self.user_repository = user_repository

    async def handle(self, game: GameSession) -> None:
        if game.game_state != GameState.game_over:
            return  # Only persist after game over

        for player_id, player_info in game.players.items():
            # Create a default dict with all power-up types set to 0
            powerup_map = {
                PowerUpType.FISH_OUT: 0,
                PowerUpType.REVEAL_LETTER: 0,
                PowerUpType.AI_MEANING: 0,
            }

            # Override with actual remaining values
            for powerup in player_info.power_ups:
                powerup_map[powerup.type] = powerup.remaining

            updates = {
                "fish_out": powerup_map[PowerUpType.FISH_OUT],
                "reveal_letter": powerup_map[PowerUpType.REVEAL_LETTER],
                "ai_meaning": powerup_map[PowerUpType.AI_MEANING],
            }

            await self.user_repository.update_user_by_device_id(
                device_id=player_id,
                updates=updates,
            )
