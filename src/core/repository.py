from sqlmodel.ext.asyncio.session import AsyncSession
from collections.abc import AsyncGenerator
import logging
from typing import TypeVar, Generic, Type, Optional, List, Dict, Any, Union
from fastapi import Depends
from sqlmodel import SQLModel, select

from sqlalchemy import delete as sqlalchemy_delete, update as sqlalchemy_update, insert as sqlalchemy_insert
from sqlalchemy.orm.attributes import flag_modified

from .query_options import QueryOptions


async def _get_async_session_dependency() -> AsyncGenerator[AsyncSession, None]:
    # pyrefly: ignore [missing-import]
    from src.database.db_connection_manager import get_mysql_manager
    manager = get_mysql_manager()
    async with manager.session() as session:
        yield session


T = TypeVar("T", bound=SQLModel)
logger = logging.getLogger(__name__)


class Repository(Generic[T]):
    """
    Generic Repository implementation for SQLModel models using AsyncSession.
    
    Example:
        repo = Repository(User, session)
        user = await repo.get(id=1)
        users = await repo.get_many(QueryOptions(filters={"xp": 10}, limit=20))
    """

    def __init__(self, model: Type[T], session: AsyncSession):
        self.model = model
        self.session = session

    def _build_select_statement(self, options: Optional[QueryOptions] = None):
        statement = select(self.model)
        if not options:
            return statement

        # Apply simple equality filters
        if options.filters:
            for key, val in options.filters.items():
                if hasattr(self.model, key):
                    statement = statement.where(getattr(self.model, key) == val)

        # Apply custom SQLAlchemy binary expressions (where)
        if options.where:
            for condition in options.where:
                statement = statement.where(condition)

        # Apply ordering
        if options.order_by:
            if isinstance(options.order_by, str):
                column = getattr(self.model, options.order_by, None)
                if column is not None:
                    statement = statement.order_by(
                        column.asc() if options.ascending else column.desc()
                    )
            elif isinstance(options.order_by, (list, tuple)):
                for item in options.order_by:
                    if isinstance(item, str):
                        column = getattr(self.model, item, None)
                        if column is not None:
                            statement = statement.order_by(
                                column.asc() if options.ascending else column.desc()
                            )
                    else:
                        statement = statement.order_by(item)
            else:
                statement = statement.order_by(
                    options.order_by.asc() if options.ascending else options.order_by.desc()
                )

        # Apply limit & offset
        if options.limit is not None:
            statement = statement.limit(options.limit)
        if options.offset is not None:
            statement = statement.offset(options.offset)

        return statement

    async def get(
        self,
        id: Optional[Any] = None,
        options: Optional[QueryOptions] = None,
    ) -> Optional[T]:
        """Fetch a single record by primary key id or by QueryOptions."""
        if id is not None:
            return await self.session.get(self.model, id)

        statement = self._build_select_statement(options)
        statement = statement.limit(1)
        result = await self.session.exec(statement)
        return result.first()

    async def get_many(
        self,
        options: Optional[QueryOptions] = None,
    ) -> List[T]:
        """Fetch multiple records matching QueryOptions."""
        statement = self._build_select_statement(options)
        result = await self.session.exec(statement)
        return list(result.all())

    async def add(self, entity: T) -> T:
        """Add a single entity to database session and commit."""
        self.session.add(entity)
        await self.session.commit()
        await self.session.refresh(entity)
        return entity

    async def add_many(self, entities: List[T], refresh: bool = False) -> List[T]:
        """
        Bulk insert entities using SQLAlchemy multi-row INSERT statement for maximum speed.
        
        Args:
            entities: List of SQLModel entities to insert.
            refresh: If True, refreshes each entity from DB (default False for high performance).
        """
        if not entities:
            return []

        dict_values = [entity.model_dump() for entity in entities]
        statement = sqlalchemy_insert(self.model).values(dict_values)
        await self.session.exec(statement)
        await self.session.commit()

        if refresh:
            for entity in entities:
                await self.session.refresh(entity)

        return entities

    async def update(
        self,
        entity: T,
        updates: Optional[Dict[str, Any]] = None,
    ) -> T:
        """Update an existing entity object with dictionary updates and commit."""
        if updates:
            for key, val in updates.items():
                if hasattr(entity, key):
                    setattr(entity, key, val)
        self.session.add(entity)
        await self.session.commit()
        await self.session.refresh(entity)
        return entity

    async def update_many(
        self,
        filters: Dict[str, Any],
        updates: Dict[str, Any],
    ) -> int:
        """Bulk update records matching filter conditions."""
        statement = sqlalchemy_update(self.model)
        for key, val in filters.items():
            if hasattr(self.model, key):
                statement = statement.where(getattr(self.model, key) == val)
        statement = statement.values(**updates)
        result = await self.session.exec(statement)
        await self.session.commit()
        return result.rowcount

    async def delete(self, entity: T) -> bool:
        """Delete a single entity."""
        await self.session.delete(entity)
        await self.session.commit()
        return True

    async def delete_many(self, filters: Dict[str, Any]) -> int:
        """Bulk delete records matching filter conditions."""
        statement = sqlalchemy_delete(self.model)
        for key, val in filters.items():
            if hasattr(self.model, key):
                statement = statement.where(getattr(self.model, key) == val)
        result = await self.session.exec(statement)
        await self.session.commit()
        return result.rowcount


class GetRepository(Generic[T]):
    """
    FastAPI dependency class that injects an AsyncSession and returns a 
    Repository[T] instance for the specified SQLModel model class.

    Usage in FastAPI route:
        @router.get("/users")
        async def get_users(
            repo: Repository[User] = Depends(GetRepository(User))
        ):
            return await repo.get_many()
    """

    def __init__(self, model: Type[T]):
        self.model = model

    def __call__(
        self,
        session: AsyncSession = Depends(_get_async_session_dependency),
    ) -> Repository[T]:
        return Repository(self.model, session)



