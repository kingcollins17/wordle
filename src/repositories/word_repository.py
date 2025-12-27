from typing import Optional, List, Dict, Any
import logging

from fastapi import Depends
from src.database.mysql_connection_manager import (
    MySQLConnectionManager,
    get_mysql_manager,
)
from src.database.redis_service import RedisService, get_redis
from src.database.query_manager import QueryManager
from src.models.word import Word

logger = logging.getLogger(__name__)

class WordRepository:
    def __init__(self, db: MySQLConnectionManager, redis: RedisService):
        self.db = db
        self.redis = redis
        self.qm = QueryManager("words")
        self.cache_ttl = 3600
        self.cache_prefix = "word"

    def _get_cache_key(self, field: str, value: str) -> str:
        return f"{self.cache_prefix}:{field}:{value}"

    async def _get_word_from_cache(self, cache_key: str) -> Optional[Dict[str, Any]]:
        try:
            cached = await self.redis.get_json(cache_key)
            if cached:
                return cached
            return None
        except Exception as e:
            logger.warning(f"Redis cache read error for key {cache_key}: {e}")
            return None

    async def _cache_word(self, cache_key: str, word_data: Dict[str, Any]) -> None:
        try:
            await self.redis.set_json(cache_key, word_data, expire_seconds=self.cache_ttl)
        except Exception as e:
            logger.warning(f"Redis cache write error for key {cache_key}: {e}")

    async def _invalidate_word_cache(self, word_data: Dict[str, Any]) -> None:
        try:
            cache_keys = []
            if "id" in word_data:
                cache_keys.append(self._get_cache_key("id", str(word_data["id"])))
            
            # Could also cache by word string itself if unique, but not strictly enforced by schema currently (though logic implies uniqueness usually)
            if "word" in word_data:
                 cache_keys.append(self._get_cache_key("word", word_data["word"]))

            redis_client = await self.redis.connect()
            if cache_keys:
                await redis_client.delete(*cache_keys)
        except Exception as e:
            logger.warning(f"Cache invalidation error: {e}")

    async def get_word_by_id(self, word_id: int) -> Optional[Dict[str, Any]]:
        cache_key = self._get_cache_key("id", str(word_id))
        cached = await self._get_word_from_cache(cache_key)
        if cached:
            return cached

        try:
            query, params = self.qm.select_one({"id": word_id})
            # Cast params to tuple as required by execute_query
            word_data = await self.db.execute_query(query, tuple(params), fetch="one")

            if word_data:
                await self._cache_word(cache_key, word_data)
                # Also cache by word text
                if "word" in word_data:
                     await self._cache_word(self._get_cache_key("word", word_data["word"]), word_data)
            
            return word_data
        except Exception as e:
            logger.error(f"Database query error for word_id {word_id}: {e}")
            raise

    async def get_word_by_text(self, text: str) -> Optional[Dict[str, Any]]:
        cache_key = self._get_cache_key("word", text)
        cached = await self._get_word_from_cache(cache_key)
        if cached:
            return cached

        try:
            query, params = self.qm.select_one({"word": text})
            word_data = await self.db.execute_query(query, tuple(params), fetch="one")

            if word_data:
                await self._cache_word(cache_key, word_data)
                if "id" in word_data:
                     await self._cache_word(self._get_cache_key("id", str(word_data["id"])), word_data)

            return word_data
        except Exception as e:
            logger.error(f"Database query error for word {text}: {e}")
            raise

    async def list_words(
        self,
        filters: Optional[Dict[str, Any]] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Word]:
        try:
            query = f"SELECT * FROM {self.qm.table}"
            values = []
            if filters:
                where_clause, where_values = self.qm._build_where_clause(filters)
                query += f" WHERE {where_clause}"
                values.extend(where_values)
            
            query += " LIMIT %s OFFSET %s"
            values.extend([limit, offset])

            res = await self.db.execute_query(query, tuple(values), fetch="all")
            # Ensure res is iterable
            if res is None:
                res = []
            return [Word(**i) for i in res]
        except Exception as e:
            logger.error(f"Error listing words: {e}")
            raise

    async def create_word(self, word_data: Dict[str, Any]) -> int:
        try:
            query, params = self.qm.insert(word_data)
            word_id = await self.db.execute_query(query, tuple(params))
            if word_id is None:
                raise ValueError("Failed to retrieve new word ID")
            
            word_data_with_id = {**word_data, "id": word_id}
            
            # Cache
            await self._cache_word(self._get_cache_key("id", str(word_id)), word_data_with_id)
            if "word" in word_data:
                await self._cache_word(self._get_cache_key("word", word_data["word"]), word_data_with_id)

            return int(word_id)
        except Exception as e:
            logger.error(f"Word creation error: {e}")
            raise

    async def update_word(self, word_id: int, updates: Dict[str, Any]) -> int:
        try:
            current_word = await self.get_word_by_id(word_id)
            
            query, params = self.qm.update(updates=updates, where={"id": word_id})
            affected = await self.db.execute_query(query, tuple(params))
            
            if current_word:
                await self._invalidate_word_cache(current_word)
            
            # Also invalidate based on the NEW values if they changed unique keys
            if updates and "word" in updates:
                 # Invalidate new word key just in case
                 await self._invalidate_word_cache({"word": updates["word"], "id": word_id})

            return int(affected) if affected is not None else 0
        except Exception as e:
            logger.error(f"Word update error for id {word_id}: {e}")
            raise

    async def delete_word(self, word_id: int) -> int:
        try:
            current_word = await self.get_word_by_id(word_id)

            query, params = self.qm.delete(where={"id": word_id})
            affected = await self.db.execute_query(query, tuple(params))

            if current_word:
                await self._invalidate_word_cache(current_word)
            
            return int(affected) if affected is not None else 0
        except Exception as e:
            logger.error(f"Word deletion error for id {word_id}: {e}")
            raise

def get_word_repository(
    mysql=Depends(get_mysql_manager), redis=Depends(get_redis)
) -> WordRepository:
    return WordRepository(db=mysql, redis=redis)
