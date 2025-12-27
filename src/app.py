from fastapi import FastAPI, HTTPException, Depends
from contextlib import asynccontextmanager
from typing import List, Dict, Any
import logging

from src.core.ai_service import AiService, get_ai_service
from .firebase_admin_setup import *
from src.core.api_tags import APITags
from src.database.mysql_connection_manager import (
    _get_mysql_manager,
    get_mysql_manager,
    startup_mysql,
    shutdown_mysql,
    MySQLConnectionManager,
)
from src.database.redis_service import (
    RedisService,
    get_redis_or_none,
    get_redis,
    startup_redis,
    shutdown_redis,
)
from src.core.env import (
    Environment,
    initialize_environment,
    get_env,
    reset_environment,
)
from src.game.websocket_manager import *
from src.game.match_making_queue import matchmaking_loop
from src.workers.lobby_cleanup_worker import (
    startup_lobby_cleanup_worker,
    shutdown_lobby_cleanup_worker,
)
from .routes import *

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan events for startup and shutdown."""
    # Startup
    try:
        # Initialize environment first
        env = initialize_environment()
        logger.info("Environment initialized successfully")
        logger.info(f"MySQL: {env.db_host}:{env.db_port}/{env.db_name}")
        logger.info(f"Redis: {env.redis_host}:{env.redis_port}/{env.redis_db}")

        # Initialize MySQL connection pool with environment
        await startup_mysql()
        logger.info("MySQL connection pool initialized")

        # Initialize Redis service with environment
        await startup_redis(env)
        logger.info("Redis service initialized")

        await startup_websocket_manager(get_redis_or_none())

        asyncio.create_task(matchmaking_loop())

        # Start the lobby cleanup worker
        mysql_manager = _get_mysql_manager()
        await startup_lobby_cleanup_worker(
            db_manager=mysql_manager,
            cleanup_interval_minutes=5,  # Run every 5 minutes
            lobby_max_age_minutes=30,  # Delete lobbies older than 30 minutes
        )
        logger.info("Lobby cleanup worker started")

    except ValueError as e:
        logger.error(f"Environment initialization failed: {e}")
        raise
    except Exception as e:
        logger.error(f"Startup failed: {e}")
        raise

    yield

    # Shutdown
    try:
        # Stop the lobby cleanup worker first
        await shutdown_lobby_cleanup_worker()
        logger.info("Lobby cleanup worker stopped")

        await shutdown_websocket_manager()
        logger.info("WebSocketManager closed")

        await shutdown_mysql()
        logger.info("MySQL connection pool closed")

        await shutdown_redis()
        logger.info("Redis service closed")

        # Reset environment (optional, mainly for testing)
        reset_environment()
        logger.info("Environment reset")

    except Exception as e:
        logger.error(f"Shutdown error: {e}")


app = FastAPI(
    title="Wordle",
    description="A highly scalable and efficient multiplayer game servier for Wordle",
    lifespan=lifespan,
)

app.include_router(auth_router)
app.include_router(game_router)
app.include_router(lb_router)
app.include_router(store_router)
app.include_router(friends_router)
app.include_router(challenges_router)
app.include_router(lobbies_router)
app.include_router(words_router)



@app.get("/health")
async def health_check(
    db_manager: MySQLConnectionManager = Depends(get_mysql_manager),
    redis_service: RedisService = Depends(get_redis),
    env: Environment = Depends(get_env),
    ai_service: AiService = Depends(get_ai_service),
):
    """Health check endpoint that verifies database, Redis, and environment."""
    # Check database health
    db_healthy = await db_manager.health_check()

    # Check Redis health
    redis_healthy = await redis_service.health_check()

    # Check environment validation
    env_valid = env.validate()

    if not db_healthy:
        raise HTTPException(status_code=500, detail="Database connection failed")

    if not redis_healthy:
        raise HTTPException(status_code=500, detail="Redis connection failed")

    if not env_valid:
        raise HTTPException(status_code=500, detail="Environment configuration invalid")

    ai_service_healthy = False
    try:
        ai_service_healthy = await ai_service.health_check()
    except:
        pass

    return {
        "status": "healthy",
        "database": "connected",
        "redis": "connected",
        "environment": {
            "mysql_host": env.db_host,
            "mysql_port": env.db_port,
            "mysql_db": env.db_name,
            "redis_host": env.redis_host,
            "redis_port": env.redis_port,
            "redis_db": env.redis_db,
            "config_valid": env_valid,
            "ai_service_healthy": ai_service_healthy,
        },
    }


@app.get("/config")
async def get_config(env: Environment = Depends(get_env)):
    """Get application configuration."""
    return {"mysql": env.get_mysql_config(), "redis": env.get_redis_config()}


@app.get("/redis/test")
async def test_redis(redis_service: RedisService = Depends(get_redis)):
    """Test Redis operations."""
    try:
        # Test basic operations
        await redis_service.set_json("test:user", {"name": "Test User", "age": 25})
        user_data = await redis_service.get_json("test:user")

        # Test list operations
        await redis_service.push_to_list(
            "test:tasks", "task1", "task2", {"priority": "high"}
        )
        tasks = await redis_service.get_list("test:tasks")

        # Test set operations
        await redis_service.add_to_set(
            "test:tags", "redis", "fastapi", {"category": "backend"}
        )
        tags = await redis_service.get_set("test:tags")

        return {
            "status": "success",
            "operations": {
                "json_storage": user_data,
                "list_storage": tasks,
                "set_storage": tags,
            },
        }
    except Exception as e:
        logger.error(f"Redis test failed: {e}")
        raise HTTPException(status_code=500, detail=f"Redis test failed: {str(e)}")
