import asyncio
import logging
from typing import Optional, AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from ..core.env import Environment, get_env, APP_CONFIG

logger = logging.getLogger(__name__)


class DBConnectionManager:
    """
    SQLAlchemy / SQLModel Async Engine and Session Manager for MySQL database.
    """

    def __init__(self, env: Environment):
        self.env = env
        self.engine: Optional[AsyncEngine] = None
        self.session_maker: Optional[async_sessionmaker[AsyncSession]] = None
        self._lock = asyncio.Lock()

    def get_database_url(self) -> str:
        """Construct mysql+aiomysql URL for SQLAlchemy/SQLModel."""
        return (
            f"mysql+aiomysql://{self.env.db_user}:{self.env.db_password}"
            f"@{self.env.db_host}:{self.env.db_port}/{self.env.db_name}?charset=utf8mb4"
        )

    async def ensure_database_exists(self):
        """Create MySQL database if it does not exist."""
        if not self.env.db_name:
            return
        server_url = (
            f"mysql+aiomysql://{self.env.db_user}:{self.env.db_password}"
            f"@{self.env.db_host}:{self.env.db_port}/?charset=utf8mb4"
        )
        try:
            temp_engine = create_async_engine(server_url, isolation_level="AUTOCOMMIT")
            async with temp_engine.connect() as conn:
                from sqlalchemy import text
                await conn.execute(text(f"CREATE DATABASE IF NOT EXISTS `{self.env.db_name}` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"))
            await temp_engine.dispose()
        except Exception as e:
            logger.warning(f"Could not auto-create database `{self.env.db_name}`: {e}")

    async def initialize(self) -> AsyncEngine:
        """Create SQLAlchemy/SQLModel AsyncEngine and async_sessionmaker."""
        if self.engine is None:
            async with self._lock:
                if self.engine is None:
                    await self.ensure_database_exists()
                    db_url = self.get_database_url()
                    self.engine = create_async_engine(
                        db_url,
                        echo=False,
                        pool_size=10,
                        max_overflow=20,
                        pool_recycle=3600,
                    )
                    self.session_maker = async_sessionmaker(
                        bind=self.engine,
                        class_=AsyncSession,
                        expire_on_commit=False,
                        autoflush=False,
                    )
                    logger.info("SQLAlchemy/SQLModel AsyncEngine & sessionmaker created successfully")
        return self.engine

    async def create_db_and_tables(self):
        """Ensure all registered SQLModel tables are loaded and created in the database."""
        # Dynamically import models to register them in SQLModel metadata without circular import
        import src.core.models  # noqa: F401

        if self.engine is None:
            await self.initialize()
        assert self.engine is not None, 'Engine should not be None'
        async with self.engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        logger.info("All SQLModel database tables created successfully")


    async def get_session(self) -> AsyncSession:
        """Create a new AsyncSession."""
        if self.session_maker is None:
            await self.initialize()
        # pyrefly: ignore [not-callable]
        return self.session_maker()

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Context manager yielding an AsyncSession with automatic transaction cleanup."""
        sess = await self.get_session()
        try:
            yield sess
        except Exception:
            await sess.rollback()
            raise
        finally:
            await sess.close()

    async def close(self):
        """Dispose of the engine connection pool."""
        if self.engine:
            await self.engine.dispose()
            self.engine = None
            self.session_maker = None
            logger.info("SQLAlchemy/SQLModel AsyncEngine disposed")


# Singleton instance
_mysql_manager: Optional[DBConnectionManager] = None


def get_mysql_manager(env: Environment=Depends(get_env)) -> DBConnectionManager:
    global _mysql_manager
    if _mysql_manager is None:
        _mysql_manager = DBConnectionManager(env)
    return _mysql_manager


async def get_async_session(
    manager: DBConnectionManager = Depends(get_mysql_manager),
) -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency function that yields an instance of AsyncSession per request."""
    async with manager.session() as session:
        yield session


# Alias for backward compatibility
get_db_session = get_async_session


async def create_db_and_tables():
    """Module-level function to create all registered SQLModel tables."""
    manager = get_mysql_manager()
    await manager.create_db_and_tables()


async def startup_db():
    """Initialize MySQL AsyncEngine and create database tables on startup."""
    env = Environment()
    manager = get_mysql_manager(env)
    await manager.initialize()
    await manager.create_db_and_tables()


async def shutdown_db():
    """Close MySQL AsyncEngine on shutdown."""
    global _mysql_manager
    if _mysql_manager:
        await _mysql_manager.close()
        _mysql_manager = None

