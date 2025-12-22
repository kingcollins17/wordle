"""
Example script to test the lobby cleanup worker independently.

This script demonstrates how to:
1. Create test lobbies with different timestamps
2. Run the cleanup worker manually
3. Verify that old lobbies are deleted

Note: This is for testing purposes only. In production, the worker
runs automatically as part of the FastAPI application lifecycle.
"""

import asyncio
import logging
from datetime import datetime, timedelta

from src.database.mysql_connection_manager import MySQLConnectionManager
from src.core.env import initialize_environment
from src.repositories.lobbies_repository import LobbiesRepository
from src.workers.lobby_cleanup_worker import LobbyCleanupWorker

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def create_test_lobbies(lobbies_repo: LobbiesRepository):
    """Create test lobbies with different ages for testing."""
    
    # Create a fresh lobby (should NOT be deleted)
    fresh_lobby = {
        "code": "FRSH",
        "p1_id": 1,
        "p1_device_id": "test-device-1",
        "p1_words": "apple,grape,peach,",
        "turn_time_limit": 120,
        "word_length": 5,
        "rounds": 3,
    }
    
    # Create an old lobby (should be deleted)
    # Note: We can't directly set created_at via the repository,
    # so this is just for demonstration. In a real test, you'd
    # need to manually update the created_at timestamp in the database.
    old_lobby = {
        "code": "OLD1",
        "p1_id": 2,
        "p1_device_id": "test-device-2",
        "p1_words": "bread,water,stone,",
        "turn_time_limit": 120,
        "word_length": 5,
        "rounds": 3,
    }
    
    try:
        fresh_id = await lobbies_repo.create_lobby(fresh_lobby)
        logger.info(f"Created fresh lobby: {fresh_lobby['code']} (ID: {fresh_id})")
        
        old_id = await lobbies_repo.create_lobby(old_lobby)
        logger.info(f"Created old lobby: {old_lobby['code']} (ID: {old_id})")
        
        # To make the old lobby actually old, you would need to run:
        # UPDATE lobbies SET created_at = NOW() - INTERVAL 31 MINUTE WHERE code = 'OLD1';
        logger.info(
            "Note: To test deletion, manually update the created_at timestamp:\n"
            "  UPDATE lobbies SET created_at = NOW() - INTERVAL 31 MINUTE WHERE code = 'OLD1';"
        )
        
        return fresh_id, old_id
        
    except Exception as e:
        logger.error(f"Error creating test lobbies: {e}")
        raise


async def test_cleanup_worker():
    """Test the lobby cleanup worker."""
    
    # Initialize environment
    env = initialize_environment()
    logger.info("Environment initialized")
    
    # Create database connection
    db_manager = MySQLConnectionManager(
        host=env.db_host,
        port=env.db_port,
        user=env.db_user,
        password=env.db_password,
        database=env.db_name,
        pool_size=5,
    )
    await db_manager.initialize()
    logger.info("Database connection initialized")
    
    try:
        # Create repository
        lobbies_repo = LobbiesRepository(db_manager)
        
        # List existing lobbies
        logger.info("\n=== Existing Lobbies ===")
        existing_lobbies = await lobbies_repo.list_lobbies(limit=10)
        for lobby in existing_lobbies:
            logger.info(
                f"  Code: {lobby.code}, Created: {lobby.created_at}, "
                f"P1: {lobby.p1_id}, P2: {lobby.p2_id}"
            )
        
        # Create test lobbies (optional)
        # await create_test_lobbies(lobbies_repo)
        
        # Create and test the cleanup worker
        logger.info("\n=== Testing Cleanup Worker ===")
        worker = LobbyCleanupWorker(
            db_manager=db_manager,
            cleanup_interval_minutes=5,
            lobby_max_age_minutes=30,
        )
        
        # Run cleanup manually (without starting the scheduler)
        await worker.cleanup_old_lobbies()
        
        # List lobbies after cleanup
        logger.info("\n=== Lobbies After Cleanup ===")
        remaining_lobbies = await lobbies_repo.list_lobbies(limit=10)
        for lobby in remaining_lobbies:
            logger.info(
                f"  Code: {lobby.code}, Created: {lobby.created_at}, "
                f"P1: {lobby.p1_id}, P2: {lobby.p2_id}"
            )
        
        logger.info("\n=== Test Complete ===")
        
    finally:
        # Clean up
        await db_manager.close()
        logger.info("Database connection closed")


if __name__ == "__main__":
    asyncio.run(test_cleanup_worker())
