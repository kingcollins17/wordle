import asyncio
import logging
from fastapi import Depends
from typing import Optional, Dict, Any, AsyncGenerator
from contextlib import asynccontextmanager
import aiomysql
from aiomysql import Pool, Connection, Cursor
from ..core.env import Environment, get_env  # Import your Environment class

logger = logging.getLogger(__name__)


class MySQLConnectionManager:
    def __init__(self, env: Environment):
        self.env = env
        self.pool: Optional[Pool] = None
        self._pool_lock = asyncio.Lock()

    async def create_pool(self) -> Pool:
        """Create a connection pool for MySQL."""
        try:
            pool = await aiomysql.create_pool(
                host=self.env.db_host,
                port=self.env.db_port,
                user=self.env.db_user,
                password=self.env.db_password,
                db=self.env.db_name,
                minsize=5,  # Minimum number of connections in pool
                maxsize=20,  # Maximum number of connections in pool
                autocommit=False,
                echo=False,
                pool_recycle=3600,  # Recycle connections after 1 hour
                charset="utf8mb4",
            )
            logger.info(f"MySQL connection pool created successfully")
            return pool
        except Exception as e:
            logger.error(f"Failed to create MySQL connection pool: {e}")
            raise

    async def get_pool(self) -> Pool:
        """Get or create the connection pool."""
        if self.pool is None:
            async with self._pool_lock:
                if self.pool is None:  # Double-check locking
                    self.pool = await self.create_pool()
        return self.pool

    @asynccontextmanager
    async def get_connection(self) -> AsyncGenerator[Connection, None]:
        """Get a connection from the pool with proper cleanup."""
        pool = await self.get_pool()
        conn = await pool.acquire()
        try:
            yield conn
        finally:
            pool.release(conn)

    @asynccontextmanager
    async def get_cursor(
        self, connection: Connection = None
    ) -> AsyncGenerator[Cursor, None]:
        """Get a cursor with automatic connection management."""
        if connection:
            # Use provided connection
            cursor = await connection.cursor(aiomysql.DictCursor)
            try:
                yield cursor
            finally:
                await cursor.close()
        else:
            # Get connection from pool
            async with self.get_connection() as conn:
                cursor = await conn.cursor()
                try:
                    yield cursor
                finally:
                    await cursor.close()

    async def execute_query(
        self, query: str, params: tuple = None, fetch: str = None
    ) -> Optional[Any]:
        """
        Execute a query with optional parameters and fetch options.

        Args:
            query: SQL query string
            params: Query parameters tuple
            fetch: 'one', 'all', or None for INSERT/UPDATE/DELETE

        Returns:
            Query results or None for non-SELECT queries
        """
        async with self.get_connection() as conn:
            async with self.get_cursor(conn) as cursor:
                try:
                    await cursor.execute(query, params)

                    if fetch == "one":
                        result = await cursor.fetchone()
                    elif fetch == "all":
                        result = await cursor.fetchall()
                    else:
                        result = cursor.rowcount

                    # Auto-commit for non-SELECT queries
                    if not query.strip().upper().startswith("SELECT"):
                        await conn.commit()

                    return result

                except Exception as e:
                    await conn.rollback()
                    logger.error(f"Query execution failed: {e}")
                    raise

    async def execute_many(self, query: str, params_list: list) -> int:
        """Execute the same query with multiple parameter sets."""
        async with self.get_connection() as conn:
            async with self.get_cursor(conn) as cursor:
                try:
                    await cursor.executemany(query, params_list)
                    await conn.commit()
                    return cursor.rowcount
                except Exception as e:
                    await conn.rollback()
                    logger.error(f"Batch execution failed: {e}")
                    raise

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[Connection, None]:
        """Context manager for database transactions."""
        async with self.get_connection() as conn:
            try:
                await conn.begin()
                yield conn
                await conn.commit()
            except Exception as e:
                await conn.rollback()
                logger.error(f"Transaction failed, rolled back: {e}")
                raise

    async def close_pool(self):
        """Close the connection pool."""
        if self.pool:
            self.pool.close()
            await self.pool.wait_closed()
            self.pool = None
            logger.info("MySQL connection pool closed")

    async def health_check(self) -> bool:
        """Check if the database connection is healthy."""
        try:
            result = await self.execute_query("SELECT 1", fetch="one")
            return result is not None
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return False


# Singleton instance
_mysql_manager: Optional[MySQLConnectionManager] = None


def _get_mysql_manager(env: Environment = None) -> MySQLConnectionManager:
    """Get or create the MySQL connection manager singleton."""
    global _mysql_manager
    if _mysql_manager is None:
        if env is None:
            env = Environment()  # Create default environment
        _mysql_manager = MySQLConnectionManager(env)
    return _mysql_manager


# Dependency to get MySQL manager (uses global environment internally)
def get_mysql_manager(
    env: Environment = Depends(get_env),
) -> MySQLConnectionManager:
    return _get_mysql_manager(env)


# FastAPI startup/shutdown handlers
async def startup_mysql():
    """Initialize MySQL connection pool on startup."""
    env = Environment()
    manager = _get_mysql_manager(env)
    await manager.get_pool()  # Initialize the pool


async def shutdown_mysql():
    """Close MySQL connection pool on shutdown."""
    global _mysql_manager
    if _mysql_manager:
        await _mysql_manager.close_pool()
        _mysql_manager = None
