from fastapi import FastAPI, HTTPException, Depends
from contextlib import asynccontextmanager
from typing import List, Dict, Any
import logging

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

        pass
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
app.include_router(words_router)



@app.get("/health")
async def health_check(
    env: Environment = Depends(get_env),
):
    """Health check endpoint that verifies database, Redis, and environment."""

    return {
        "status": "healthy",
    }
