from src.core.utils.time import get_current_time
import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import Depends
from sqlalchemy.orm.attributes import flag_modified

from src.core.models import Game, User, Word
from src.core.models.game import GameStatus, Player
from src.core.repository import GetRepository, Repository
from src.core.query_options import QueryOptions
from src.game.game_algorithm import GameAlgorithm, PowerUpType
from src.game.game_events import GameEvent, GameEventType, PowerUpUsageResult
from .websocket_manager import WebSocketManager, get_websocket_manager

logger = logging.getLogger(__name__)


class GameError(Exception):
    """Custom exception for game-related errors."""
    pass


class GameManager:
    """
    Manages a single game session's lifecycle.

    All state lives in the Game database model. Each public method:
      1. Loads the Game from DB
      2. Validates & mutates
      3. Persists back to DB
      4. Broadcasts a GameEvent to both players via WebSocket
    """

    def __init__(
        self,
        game_id: str,
        websocket_manager: WebSocketManager,
        game_repo: Repository[Game],
        user_repo: Repository[User],
        word_repo: Repository[Word],
    ):
        self.game_id = game_id
        self.ws = websocket_manager
        self.game_repo = game_repo
        self.user_repo = user_repo
        self.word_repo = word_repo
        self.algorithm = GameAlgorithm()

    # ── Helpers ──────────────────────────────────────────────────────────

    async def _get_game(self) -> Game:
        """Load Game from DB or raise."""
        game = await self.game_repo.get(id=self.game_id)
        if game is None:
            raise GameError(f"Game {self.game_id} not found")
        return game

    async def _save(self, game: Game) -> Game:
        """Persist Game changes to DB."""
        game.updated_at = get_current_time()
        return await self.game_repo.update(game)

    def _game_to_dict(self, game: Game) -> dict:
        """Serialize Game to a dict for broadcasting (excludes secret words)."""
        return {
            "id": game.id,
            "status": game.status,
            "current_turn": game.current_turn,
            "player_1": game.player_1,
            "player_2": game.player_2,
            "current_round": game.current_round,
            "total_rounds": game.total_rounds,
            "max_attempts": game.max_attempts,
            "word_length": game.word_length,
            "player_1_score": game.player_1_score,
            "player_2_score": game.player_2_score,
            "player_1_attempts": game.player_1_attempts,
            "player_2_attempts": game.player_2_attempts,
            "player_1_fish_outs": game.player_1_fish_outs,
            "player_2_fish_outs": game.player_2_fish_outs,
            "player_1_reveal_letters": game.player_1_reveal_letters,
            "player_2_reveal_letters": game.player_2_reveal_letters,
            "player_1_meanings": game.player_1_meanings,
            "player_2_meanings": game.player_2_meanings,
            "winner_id": game.winner_id,
        }

    async def _broadcast(self, game: Game, event_type: GameEventType, payload: dict | None = None) -> GameEvent:
        """Build a GameEvent, broadcast to both players, and return it."""
        event = GameEvent(
            event_type=event_type,
            game_state=self._game_to_dict(game),
            payload=payload,
        )
        player_ids = [game.player_1]
        if game.player_2:
            player_ids.append(game.player_2)
        await self.ws.broadcast(event, user_ids=player_ids)
        return event

    def _get_player_attrs(self, game: Game, player_id: str) -> tuple[str, str]:
        """
        Return the prefix pair (player_prefix, opponent_prefix) for a given player_id.
        e.g. ("player_1", "player_2") or ("player_2", "player_1").
        """
        if player_id == game.player_1:
            return ("player_1", "player_2")
        elif player_id == game.player_2:
            return ("player_2", "player_1")
        raise GameError(f"Player {player_id} is not in this game")

    def _validate_in_progress(self, game: Game) -> None:
        if game.status != GameStatus.IN_PROGRESS:
            raise GameError("Game is not in progress")

    def _validate_turn(self, game: Game, player_id: str) -> None:
        if not game.current_turn:
            raise GameError("Game has no current turn")

        turn_map = {Player.p1: game.player_1, Player.p2: game.player_2}
        current_player_id = turn_map.get(game.current_turn)
        if current_player_id != player_id:
            raise GameError("It is not your turn")

    def _get_secret_word(self, game: Game, opponent_prefix: str) -> str:
        """Get the opponent's secret word for the current round."""
        words: List[str] = getattr(game, f"{opponent_prefix}_words", [])
        idx = game.current_round - 1
        if idx >= len(words):
            raise GameError("No secret word for this round")
        return words[idx]

    # ── Public API ───────────────────────────────────────────────────────

    async def get_game_state(self) -> dict:
        """Return the current game state as a dict."""
        game = await self._get_game()
        return self._game_to_dict(game)

    async def make_guess(self, player_id: str, guess: str) -> GameEvent:
        """
        Process a guess.

        The current player guesses their opponent's secret word.
        - Correct guess → score +1, handle turn/round end
        - Max attempts reached → turn switches or round ends
        - Otherwise → same player keeps guessing
        """
        game = await self._get_game()
        self._validate_in_progress(game)
        self._validate_turn(game, player_id)

        if len(guess) != game.word_length:
            raise GameError(f"Guess must be {game.word_length} letters")

        player_prefix, opponent_prefix = self._get_player_attrs(game, player_id)
        secret_word = self._get_secret_word(game, opponent_prefix)

        # Evaluate
        result = self.algorithm.evaluate_guess(secret_word, guess)

        # Record attempt as full evaluated dictionary (guess + evaluated result)
        attempt_record = {
            "guess": guess,
            "result": result.model_dump(),
        }

        if player_id == game.player_1:
            if game.player_1_attempts is None:
                game.player_1_attempts = []
            game.player_1_attempts.append(attempt_record)
            flag_modified(game, "player_1_attempts")
            attempts_count = len(game.player_1_attempts)
        else:
            if game.player_2_attempts is None:
                game.player_2_attempts = []
            game.player_2_attempts.append(attempt_record)
            flag_modified(game, "player_2_attempts")
            attempts_count = len(game.player_2_attempts)

        if result.is_correct():
            # Player guessed correctly — score +1, won turn
            if player_id == game.player_1:
                game.player_1_score += 1
            else:
                game.player_2_score += 1
            event_type, payload = self._handle_turn_won(game, player_id)
            payload["guess_result"] = result.model_dump()
        elif attempts_count >= game.max_attempts:
            # Out of attempts — lost turn
            event_type, payload = self._handle_turn_lost(game, player_id)
            payload["guess_result"] = result.model_dump()
        else:
            # Keep guessing
            event_type = GameEventType.GUESS_MADE
            payload = {"guess": guess, "guess_result": result.model_dump()}

        await self._save(game)
        return await self._broadcast(game, event_type, payload)

    def _reset_round_state(self, game: Game) -> None:
        """Reset all round gameplay and powerup tracking state for both players when advancing rounds."""
        game.player_1_attempts = []
        game.player_2_attempts = []
        game.player_1_fish_outs = []
        game.player_2_fish_outs = []
        game.player_1_reveal_letters = []
        game.player_2_reveal_letters = []
        game.player_1_meanings = {}
        game.player_2_meanings = {}

    def _handle_turn_won(self, game: Game, player_id: str) -> tuple[GameEventType, dict]:
        """
        Player guessed correctly and won their turn.
        Switches turn to opponent or advances round if both players completed their turn.
        """
        if game.current_turn == Player.p1:
            game.current_turn = Player.p2
            return GameEventType.TURN_CHANGED, {
                "won_by": player_id,
                "current_turn": Player.p2.value,
            }
        else:
            is_last_round = game.current_round >= game.total_rounds
            if is_last_round:
                return self._finalize_game(game)
            else:
                game.current_round += 1
                game.current_turn = Player.p1
                self._reset_round_state(game)
                return GameEventType.ROUND_ENDED, {
                    "won_by": player_id,
                    "new_round": game.current_round,
                }

    def _handle_turn_lost(self, game: Game, player_id: str) -> tuple[GameEventType, dict]:
        """
        Player ran out of attempts and lost their turn.
        Switches turn to opponent or advances round / ends game if both players completed their turn.
        """
        if game.current_turn == Player.p1:
            game.current_turn = Player.p2
            return GameEventType.TURN_LOST, {
                "lost_by": player_id,
                "current_turn": Player.p2.value,
            }
        else:
            is_last_round = game.current_round >= game.total_rounds
            if is_last_round:
                return self._finalize_game(game)
            else:
                game.current_round += 1
                game.current_turn = Player.p1
                self._reset_round_state(game)
                return GameEventType.TURN_LOST, {
                    "lost_by": player_id,
                    "new_round": game.current_round,
                }

    def _finalize_game(self, game: Game) -> tuple[GameEventType, dict]:
        """Determine winner by score and mark game as over."""
        game.status = GameStatus.GAME_OVER
        game.completed_at = get_current_time()

        if game.player_1_score > game.player_2_score:
            game.winner_id = game.player_1
            reason = f"Player 1 wins {game.player_1_score}-{game.player_2_score}"
        elif game.player_2_score > game.player_1_score:
            game.winner_id = game.player_2
            reason = f"Player 2 wins {game.player_2_score}-{game.player_1_score}"
        else:
            game.winner_id = None
            reason = f"Draw at {game.player_1_score}-{game.player_2_score}"

        return GameEventType.GAME_OVER, {
            "winner_id": game.winner_id,
            "reason": reason,
            "player_1_score": game.player_1_score,
            "player_2_score": game.player_2_score,
        }

    async def use_powerup(self, player_id: str, powerup_type: PowerUpType) -> PowerUpUsageResult:
        """
        Use a power-up. Decrements the user's count in the User table
        and applies the effect via GameAlgorithm.

        Returns a PowerUpUsageResult with the relevant field populated.
        """
        game = await self._get_game()
        self._validate_in_progress(game)
        self._validate_turn(game, player_id)

        # Check & decrement user's powerup in DB
        user = await self.user_repo.get(id=player_id)
        if user is None:
            raise GameError(f"User {player_id} not found")

        field_map = {
            PowerUpType.FISH_OUT: "fish_out",
            PowerUpType.REVEAL_LETTER: "reveal_letter",
            PowerUpType.WORD_MEANING: "word_meaning",
        }
        field_name = field_map[powerup_type]
        remaining = getattr(user, field_name, 0)
        if remaining <= 0:
            raise GameError(f"No {powerup_type.value} power-ups remaining")
        await self.user_repo.update(user, {field_name: remaining - 1})

        # Get opponent's secret word
        player_prefix, opponent_prefix = self._get_player_attrs(game, player_id)
        secret_word = self._get_secret_word(game, opponent_prefix)

        # Apply effect
        result = PowerUpUsageResult(powerup_type=powerup_type)

        if powerup_type == PowerUpType.FISH_OUT:
            attr_name = f"{player_prefix}_fish_outs"
            already_fished: List[str] = getattr(game, attr_name) or []
            letter = self.algorithm.fishout(secret_word, already_fished)
            new_fished = list(already_fished) + [letter]
            setattr(game, attr_name, new_fished)
            flag_modified(game, attr_name)
            result.fished_letter = letter

        elif powerup_type == PowerUpType.REVEAL_LETTER:
            attr_name = f"{player_prefix}_reveal_letters"
            already_revealed: List[str] = getattr(game, attr_name) or []
            revealed_indices = [
                int(entry.split(":")[0])
                for entry in already_revealed
                if ":" in entry and entry.split(":")[0].isdigit()
            ]
            letter, index = self.algorithm.reveal_letter(secret_word, revealed_indices)
            new_revealed = list(already_revealed) + [f"{index}:{letter}"]
            setattr(game, attr_name, new_revealed)
            flag_modified(game, attr_name)
            result.revealed_letter = letter
            result.revealed_index = index

        elif powerup_type == PowerUpType.WORD_MEANING:
            attr_name = f"{player_prefix}_meanings"
            meanings: dict = dict(getattr(game, attr_name) or {})
            upper_word = secret_word.upper()
            if upper_word not in meanings:
                # Look up meaning from Word table
                word_record = await self.word_repo.get(
                    options=QueryOptions(filters={"word": secret_word})
                )
                meaning = word_record.meaning if word_record and word_record.meaning else "Meaning not available"
                meanings[upper_word] = meaning
                setattr(game, attr_name, meanings)
                flag_modified(game, attr_name)
            result.word_meaning = meanings[upper_word]

        await self._save(game)
        await self._broadcast(game, GameEventType.POWERUP_USED, result.model_dump())
        return result

    async def pause_game(self, player_id: str) -> GameEvent:
        """Pause the game. Only works while in progress."""
        game = await self._get_game()
        self._validate_in_progress(game)
        self._get_player_attrs(game, player_id)  # validate player is in game

        game.status = GameStatus.PAUSED
        await self._save(game)
        return await self._broadcast(game, GameEventType.GAME_PAUSED, {"paused_by": player_id})

    async def resume_game(self, player_id: str) -> GameEvent:
        """Resume a paused game."""
        game = await self._get_game()
        if game.status != GameStatus.PAUSED:
            raise GameError("Game is not paused")
        self._get_player_attrs(game, player_id)  # validate player is in game

        game.status = GameStatus.IN_PROGRESS
        await self._save(game)
        return await self._broadcast(game, GameEventType.GAME_RESUMED, {"resumed_by": player_id})

    async def end_game(self, reason: str = "Game ended") -> GameEvent:
        """Force-end the game. Winner determined by current scores."""
        game = await self._get_game()
        if game.status == GameStatus.GAME_OVER:
            raise GameError("Game is already over")

        event_type, payload = self._finalize_game(game)
        payload["reason"] = reason

        await self._save(game)
        return await self._broadcast(game, event_type, payload)


# ── FastAPI Dependency ───────────────────────────────────────────────────────


class GetGameManager:
    """FastAPI dependency that constructs a GameManager for a given game_id."""
        

    def __call__(
        self,
        game_id: str,
        websocket_manager: WebSocketManager = Depends(get_websocket_manager),
        game_repo: Repository[Game] = Depends(GetRepository(Game)),
        user_repo: Repository[User] = Depends(GetRepository(User)),
        word_repo: Repository[Word] = Depends(GetRepository(Word)),
    ) -> GameManager:
        return GameManager(
            game_id=game_id,
            websocket_manager=websocket_manager,
            game_repo=game_repo,
            user_repo=user_repo,
            word_repo=word_repo,
        )
