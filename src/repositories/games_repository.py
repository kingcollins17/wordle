# src/repositories/games_repository.py

import logging
from typing import Optional, List, Dict, Any
from fastapi import Depends

from src.database.mysql_connection_manager import (
    MySQLConnectionManager,
    get_mysql_manager,
)
from src.database.query_manager import QueryManager
from ..models.game import Game

logger = logging.getLogger(__name__)


class GamesRepository:
    def __init__(self, db: MySQLConnectionManager):
        self.db = db
        self.qm = QueryManager("games")

    async def get_game_by_id(self, game_id: int) -> Optional[Game]:
        """Fetch a single game by ID."""
        try:
            query, params = self.qm.select_one({"id": game_id})
            game_data = await self.db.execute_query(query, params, fetch="one")
            return Game(**game_data) if game_data else None
        except Exception as e:
            logger.error(f"DB error get_game_by_id {game_id}: {e}")
            raise

    async def list_games(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 50,
        offset: int = 0,
        order_by: str = "completed_at",
        ascending: bool = False,
    ) -> List[Game]:
        """Fetch many games with optional filters, pagination, and sorting."""
        try:
            query = f"SELECT * FROM {self.qm.table}"
            values = []

            if filters:
                where_clause, where_values = self.qm._build_where_clause(filters)
                query += f" WHERE {where_clause}"
                values.extend(where_values)

            if order_by:
                direction = "ASC" if ascending else "DESC"
                query += f" ORDER BY {order_by} {direction}"

            query += " LIMIT %s OFFSET %s"
            values.extend([limit, offset])

            rows = await self.db.execute_query(query, values, fetch="all")
            return [Game(**row) for row in rows]
        except Exception as e:
            logger.error(f"Error listing games: {e}")
            raise

    async def create_game(self, game_data: Dict[str, Any]) -> int:
        """Insert a single game and return its ID."""
        try:
            query, params = self.qm.insert(game_data)
            game_id = await self.db.execute_query(query, params)
            logger.info(f"Game created with ID: {game_id}")
            return game_id
        except Exception as e:
            logger.error(f"Game creation error: {e}")
            raise

    async def create_many_games(self, games_data: List[Dict[str, Any]]) -> List[int]:
        """Insert multiple games and return their IDs."""
        try:
            ids = []
            for game_data in games_data:
                query, params = self.qm.insert(game_data)
                game_id = await self.db.execute_query(query, params)
                ids.append(game_id)
            return ids
        except Exception as e:
            logger.error(f"Error creating multiple games: {e}")
            raise

    async def update_game(self, game_id: int, updates: Dict[str, Any]) -> int:
        """Update a game by ID."""
        try:
            query, params = self.qm.update(updates=updates, where={"id": game_id})
            affected = await self.db.execute_query(query, params)
            return affected
        except Exception as e:
            logger.error(f"Error updating game {game_id}: {e}")
            raise

    async def delete_game(self, game_id: int) -> int:
        """Delete a game by ID."""
        try:
            query, params = self.qm.delete(where={"id": game_id})
            affected = await self.db.execute_query(query, params)
            return affected
        except Exception as e:
            logger.error(f"Error deleting game {game_id}: {e}")
            raise


def get_games_repository(mysql=Depends(get_mysql_manager)) -> GamesRepository:
    """Dependency injector for GamesRepository"""
    return GamesRepository(db=mysql)
