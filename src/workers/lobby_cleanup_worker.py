# src/workers/lobby_cleanup_worker.py

import logging
from datetime import datetime, timedelta
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.repositories.lobbies_repository import LobbiesRepository
from src.database.mysql_connection_manager import MySQLConnectionManager

logger = logging.getLogger(__name__)


class LobbyCleanupWorker:
    """
    Background worker that periodically deletes lobbies older than 30 minutes.
    Uses APScheduler to run cleanup tasks at regular intervals.
    """

    def __init__(
        self,
        db_manager: MySQLConnectionManager,
        cleanup_interval_minutes: int = 5,
        lobby_max_age_minutes: int = 30,
    ):
        """
        Initialize the lobby cleanup worker.

        Args:
            db_manager: MySQL connection manager for database access
            cleanup_interval_minutes: How often to run the cleanup job (default: 5 minutes)
            lobby_max_age_minutes: Maximum age of lobbies before deletion (default: 30 minutes)
        """
        self.db_manager = db_manager
        self.cleanup_interval_minutes = cleanup_interval_minutes
        self.lobby_max_age_minutes = lobby_max_age_minutes
        self.scheduler: Optional[AsyncIOScheduler] = None
        self.lobbies_repo = LobbiesRepository(db_manager)

    async def cleanup_old_lobbies(self):
        """
        Delete lobbies that are older than the configured maximum age.
        This method is called periodically by the scheduler.
        """
        try:
            # Calculate the cutoff time (current time - max age)
            cutoff_time = datetime.now() - timedelta(minutes=self.lobby_max_age_minutes)
            
            logger.info(
                f"Starting lobby cleanup job. Deleting lobbies created before {cutoff_time}"
            )

            # Fetch all lobbies (we'll filter by created_at)
            # Note: We could optimize this with a custom query, but for now we'll use the existing methods
            all_lobbies = await self.lobbies_repo.list_lobbies(
                limit=1000,  # Adjust as needed
                order_by="created_at",
                ascending=True,  # Oldest first
            )

            deleted_count = 0
            for lobby in all_lobbies:
                # Check if lobby is older than cutoff time
                if lobby.created_at and lobby.created_at < cutoff_time:
                    try:
                        # Delete the lobby by ID
                        affected = await self.lobbies_repo.delete_lobby_by_id(lobby.id)
                        if affected > 0:
                            deleted_count += 1
                            logger.info(
                                f"Deleted old lobby: code={lobby.code}, "
                                f"created_at={lobby.created_at}, id={lobby.id}"
                            )
                    except Exception as e:
                        logger.error(
                            f"Failed to delete lobby {lobby.code} (id={lobby.id}): {e}"
                        )
                else:
                    # Since lobbies are ordered by created_at (oldest first),
                    # we can break early once we hit a lobby that's not old enough
                    break

            logger.info(
                f"Lobby cleanup job completed. Deleted {deleted_count} old lobbies."
            )

        except Exception as e:
            logger.error(f"Error during lobby cleanup job: {e}")
            import traceback
            traceback.print_exc()

    async def cleanup_old_lobbies_optimized(self):
        """
        Optimized version: Delete lobbies using a single SQL query.
        This is more efficient than fetching all lobbies and deleting them one by one.
        """
        try:
            # Calculate the cutoff time (current time - max age)
            cutoff_time = datetime.now() - timedelta(minutes=self.lobby_max_age_minutes)
            
            logger.info(
                f"Starting optimized lobby cleanup job. Deleting lobbies created before {cutoff_time}"
            )

            # Use a direct SQL DELETE query for better performance
            query = """
                DELETE FROM lobbies 
                WHERE created_at < %s
            """
            
            async with self.db_manager.get_connection() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute(query, (cutoff_time,))
                    deleted_count = cursor.rowcount
                    await conn.commit()
            
            logger.info(
                f"Optimized lobby cleanup job completed. Deleted {deleted_count} old lobbies."
            )

        except Exception as e:
            logger.error(f"Error during optimized lobby cleanup job: {e}")
            import traceback
            traceback.print_exc()

    def start(self):
        """
        Start the background scheduler.
        This should be called during application startup.
        """
        if self.scheduler is not None:
            logger.warning("Lobby cleanup worker is already running")
            return

        self.scheduler = AsyncIOScheduler()
        
        # Add the cleanup job to run at the specified interval
        # Using the optimized version for better performance
        self.scheduler.add_job(
            self.cleanup_old_lobbies_optimized,  # Use optimized version
            trigger=IntervalTrigger(minutes=self.cleanup_interval_minutes),
            id="lobby_cleanup",
            name="Cleanup old lobbies",
            replace_existing=True,
        )

        self.scheduler.start()
        logger.info(
            f"Lobby cleanup worker started. "
            f"Running every {self.cleanup_interval_minutes} minutes, "
            f"deleting lobbies older than {self.lobby_max_age_minutes} minutes."
        )

    def shutdown(self):
        """
        Shutdown the background scheduler.
        This should be called during application shutdown.
        """
        if self.scheduler is None:
            logger.warning("Lobby cleanup worker is not running")
            return

        self.scheduler.shutdown(wait=True)
        self.scheduler = None
        logger.info("Lobby cleanup worker stopped")


# Global instance
_lobby_cleanup_worker: Optional[LobbyCleanupWorker] = None


def get_lobby_cleanup_worker() -> Optional[LobbyCleanupWorker]:
    """
    Get the global lobby cleanup worker instance.
    
    Returns:
        The lobby cleanup worker instance, or None if not initialized
    """
    return _lobby_cleanup_worker


async def startup_lobby_cleanup_worker(
    db_manager: MySQLConnectionManager,
    cleanup_interval_minutes: int = 5,
    lobby_max_age_minutes: int = 30,
):
    """
    Initialize and start the lobby cleanup worker.
    Should be called during application startup.

    Args:
        db_manager: MySQL connection manager
        cleanup_interval_minutes: How often to run cleanup (default: 5 minutes)
        lobby_max_age_minutes: Maximum age of lobbies (default: 30 minutes)
    """
    global _lobby_cleanup_worker

    if _lobby_cleanup_worker is not None:
        logger.warning("Lobby cleanup worker already initialized")
        return

    _lobby_cleanup_worker = LobbyCleanupWorker(
        db_manager=db_manager,
        cleanup_interval_minutes=cleanup_interval_minutes,
        lobby_max_age_minutes=lobby_max_age_minutes,
    )
    _lobby_cleanup_worker.start()
    logger.info("Lobby cleanup worker initialized and started")


async def shutdown_lobby_cleanup_worker():
    """
    Shutdown the lobby cleanup worker.
    Should be called during application shutdown.
    """
    global _lobby_cleanup_worker

    if _lobby_cleanup_worker is None:
        logger.warning("Lobby cleanup worker not initialized")
        return

    _lobby_cleanup_worker.shutdown()
    _lobby_cleanup_worker = None
    logger.info("Lobby cleanup worker shut down")
