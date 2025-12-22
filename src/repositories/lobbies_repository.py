# src/repositories/lobbies_repository.py

import logging
from typing import Optional, List, Dict, Any
from fastapi import Depends

from src.database.mysql_connection_manager import (
    MySQLConnectionManager,
    get_mysql_manager,
)
from src.database.query_manager import QueryManager
from ..models.lobby import DatabaseLobby  # ty:ignore[unresolved-import]

logger = logging.getLogger(__name__)


class LobbiesRepository:
    """Repository for managing lobby data in the database"""
    
    def __init__(self, db: MySQLConnectionManager):
        self.db = db
        self.qm = QueryManager("lobbies")

    async def get_lobby_by_code(self, code: str) -> Optional[DatabaseLobby]:
        """Fetch a lobby by its code.
        
        Args:
            code: The 4-character lobby code
            
        Returns:
            DatabaseLobby if found, None otherwise
        """
        try:
            query, params = self.qm.select_one({"code": code})
            lobby_data = await self.db.execute_query(query, params, fetch="one")
            return DatabaseLobby(**lobby_data) if lobby_data else None
        except Exception as e:
            logger.error(f"DB error get_lobby_by_code {code}: {e}")
            raise

    async def get_lobby_by_id(self, lobby_id: int) -> Optional[DatabaseLobby]:
        """Fetch a lobby by its ID.
        
        Args:
            lobby_id: The lobby ID
            
        Returns:
            DatabaseLobby if found, None otherwise
        """
        try:
            query, params = self.qm.select_one({"id": lobby_id})
            lobby_data = await self.db.execute_query(query, params, fetch="one")
            return DatabaseLobby(**lobby_data) if lobby_data else None
        except Exception as e:
            logger.error(f"DB error get_lobby_by_id {lobby_id}: {e}")
            raise

    async def create_lobby(self, lobby_data: Dict[str, Any]) -> int:
        """Create a new lobby and return its ID.
        
        Args:
            lobby_data: Dictionary containing lobby fields
            
        Returns:
            The ID of the created lobby
        """
        try:
            query, params = self.qm.insert(lobby_data)
            lobby_id = await self.db.execute_query(query, params)
            logger.info(f"Lobby created with ID: {lobby_id}, code: {lobby_data.get('code')}")
            return lobby_id
        except Exception as e:
            logger.error(f"Lobby creation error: {e}")
            raise

    async def update_lobby(self, code: str, updates: Dict[str, Any]) -> int:
        """Update a lobby by its code.
        
        Args:
            code: The lobby code
            updates: Dictionary of fields to update
            
        Returns:
            Number of affected rows
        """
        try:
            query, params = self.qm.update(updates=updates, where={"code": code})
            affected = await self.db.execute_query(query, params)
            logger.info(f"Lobby {code} updated, affected rows: {affected}")
            return affected
        except Exception as e:
            logger.error(f"Error updating lobby {code}: {e}")
            raise

    async def update_lobby_by_id(self, lobby_id: int, updates: Dict[str, Any]) -> int:
        """Update a lobby by its ID.
        
        Args:
            lobby_id: The lobby ID
            updates: Dictionary of fields to update
            
        Returns:
            Number of affected rows
        """
        try:
            query, params = self.qm.update(updates=updates, where={"id": lobby_id})
            affected = await self.db.execute_query(query, params)
            logger.info(f"Lobby ID {lobby_id} updated, affected rows: {affected}")
            return affected
        except Exception as e:
            logger.error(f"Error updating lobby {lobby_id}: {e}")
            raise

    async def delete_lobby(self, code: str) -> int:
        """Delete a lobby by its code.
        
        Args:
            code: The lobby code
            
        Returns:
            Number of affected rows
        """
        try:
            query, params = self.qm.delete(where={"code": code})
            affected = await self.db.execute_query(query, params)
            logger.info(f"Lobby {code} deleted, affected rows: {affected}")
            return affected
        except Exception as e:
            logger.error(f"Error deleting lobby {code}: {e}")
            raise

    async def delete_lobby_by_id(self, lobby_id: int) -> int:
        """Delete a lobby by its ID.
        
        Args:
            lobby_id: The lobby ID
            
        Returns:
            Number of affected rows
        """
        try:
            query, params = self.qm.delete(where={"id": lobby_id})
            affected = await self.db.execute_query(query, params)
            logger.info(f"Lobby ID {lobby_id} deleted, affected rows: {affected}")
            return affected
        except Exception as e:
            logger.error(f"Error deleting lobby {lobby_id}: {e}")
            raise

    async def list_lobbies(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 50,
        offset: int = 0,
        order_by: str = "created_at",
        ascending: bool = False,
    ) -> List[DatabaseLobby]:
        """Fetch many lobbies with optional filters, pagination, and sorting.
        
        Args:
            filters: Optional dictionary of filter conditions
            limit: Maximum number of records to return
            offset: Number of records to skip
            order_by: Field to sort by
            ascending: Sort order (True for ascending, False for descending)
            
        Returns:
            List of DatabaseLobby objects
        """
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
            return [DatabaseLobby(**row) for row in rows]
        except Exception as e:
            logger.error(f"Error listing lobbies: {e}")
            raise

    async def get_user_active_lobby(self, user_id: int) -> Optional[DatabaseLobby]:
        """Get the active lobby for a user (where they are p1 or p2).
        
        Args:
            user_id: The user's ID
            
        Returns:
            DatabaseLobby if found, None otherwise
        """
        try:
            query = f"""
                SELECT * FROM {self.qm.table} 
                WHERE p1_id = %s OR p2_id = %s 
                ORDER BY created_at DESC 
                LIMIT 1
            """
            params = [user_id, user_id]
            lobby_data = await self.db.execute_query(query, params, fetch="one")
            return DatabaseLobby(**lobby_data) if lobby_data else None
        except Exception as e:
            logger.error(f"Error getting active lobby for user {user_id}: {e}")
            raise

    async def get_user_active_lobby_by_device_id(self, device_id: str) -> Optional[DatabaseLobby]:
        """Get the active lobby for a user by device_id (where they are p1 or p2).
        
        Args:
            device_id: The user's device ID
            
        Returns:
            DatabaseLobby if found, None otherwise
        """
        try:
            query = f"""
                SELECT * FROM {self.qm.table} 
                WHERE p1_device_id = %s OR p2_device_id = %s 
                ORDER BY created_at DESC 
                LIMIT 1
            """
            params = [device_id, device_id]
            lobby_data = await self.db.execute_query(query, params, fetch="one")
            return DatabaseLobby(**lobby_data) if lobby_data else None
        except Exception as e:
            logger.error(f"Error getting active lobby for device_id {device_id}: {e}")
            raise


def get_lobbies_repository(mysql=Depends(get_mysql_manager)) -> LobbiesRepository:
    """Dependency injector for LobbiesRepository"""
    return LobbiesRepository(db=mysql)
