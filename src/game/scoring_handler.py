from src.models import GameSession, GameState, PlayerRole, AfterGameHandler
from src.repositories import UserRepository


class ScoringAfterGameHandler(AfterGameHandler):
    """
    Handles scoring after the game ends.
    Responsible for calculating and updating the XP and coins of each player.
    """

    def __init__(self, user_repository: UserRepository):
        super().__init__()
        self.user_repository = user_repository

    @staticmethod
    def calculate_xp(attempts: int, won: bool) -> int:
        """
        Calculate XP for a player based on number of attempts and game outcome.
        """
        MAX_XP = 100
        MIN_XP = 20
        CONSOLATION_XP = 10

        if not won:
            return CONSOLATION_XP

        xp = MAX_XP - (attempts - 1) * 15
        return max(xp, MIN_XP)

    @staticmethod
    def calculate_coins(attempts: int, won: bool) -> int:
        """
        Calculate coins for a player based on number of attempts and game outcome.
        """
        WIN_BASE_COINS = 20
        CONSOLATION_COINS = 5

        if not won:
            return CONSOLATION_COINS

        # More coins for fewer attempts
        coins = WIN_BASE_COINS - (attempts - 1) * 3
        return max(coins, 5)

    async def handle(self, game: GameSession) -> None:
        if game.game_state != GameState.game_over or not game.outcome:
            return  # Only proceed if game is over and outcome exists

        for player_id, player_info in game.players.items():
            won = game.outcome.winner_id == player_id
            attempts = len(player_info.attempts)

            gained_xp = self.calculate_xp(attempts, won)
            gained_coins = self.calculate_coins(attempts, won)

            user = await self.user_repository.get_user_by_device_id(player_id)
            if not user:
                continue  # User not found, skip

            updated_xp = user.get("xp", 0) + gained_xp
            updated_coins = user.get("coins", 0) + gained_coins

            await self.user_repository.update_user_by_device_id(
                device_id=player_id,
                updates={"xp": updated_xp, "coins": updated_coins},
            )
