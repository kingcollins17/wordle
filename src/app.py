from fastapi import FastAPI, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from typing import List, Dict, Any
import logging
import os

from .firebase_admin_setup import *
from src.core.api_tags import APITags
from src.database.db_connection_manager import startup_db


from src.core.env import (
    Environment,
    initialize_environment,
    get_env,
    reset_environment,
)
from src.game.websocket_manager import *

from .routes import *

from src.core.services.word_service import seed_initial_words

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
        await startup_db()
        setup_firebase()
        logger.info("MySQL connection pool initialized")

        # Start WebSocket message cache cleanup background task
        websocket_manager.start_cleanup_task()

        # Seed initial word dictionaries (fours, fives, sixes) on startup
        # await seed_initial_words()


    except ValueError as e:
        logger.error(f"Environment initialization failed: {e}")
        raise
    except Exception as e:
        logger.error(f"Startup failed: {e}")
        raise

    yield

    # Shutdown
    try:
        await websocket_manager.stop_cleanup_task()
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
app.include_router(words_router)
app.include_router(rewards_router)


well_known_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".well-known"))
os.makedirs(well_known_dir, exist_ok=True)
app.mount("/.well-known", StaticFiles(directory=well_known_dir), name="well-known")



@app.get("/health")
async def health_check(
    env: Environment = Depends(get_env),
):
    """Health check endpoint that verifies database, Redis, and environment."""

    return {
        "status": "healthy",
        "ws": "https://domain/game/ws?user_id=<USERID>"
    }
