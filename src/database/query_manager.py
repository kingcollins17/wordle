from typing import List, Dict, Any, Optional, Tuple


class QueryManager:
    def __init__(self, table: str):
        self.table = table

    def select_one(self, where: Dict[str, Any]) -> Tuple[str, List[Any]]:
        where_clause, values = self._build_where_clause(where)
        query = f"SELECT * FROM {self.table} WHERE {where_clause} LIMIT 1;"
        return query, values

    def select_many(
        self, where: Optional[Dict[str, Any]] = None, limit: Optional[int] = None
    ) -> Tuple[str, List[Any]]:
        where_clause, values = self._build_where_clause(where) if where else ("1", [])
        query = f"SELECT * FROM {self.table} WHERE {where_clause}"
        if limit:
            query += f" LIMIT {limit}"
        query += ";"
        return query, values

    def insert(self, data: Dict[str, Any]) -> Tuple[str, List[Any]]:
        keys = ", ".join(data.keys())
        placeholders = ", ".join(["%s"] * len(data))
        values = list(data.values())
        query = f"INSERT INTO {self.table} ({keys}) VALUES ({placeholders});"
        return query, values

    def update(
        self, updates: Dict[str, Any], where: Dict[str, Any]
    ) -> Tuple[str, List[Any]]:
        set_clause = ", ".join([f"{k} = %s" for k in updates])
        where_clause, where_values = self._build_where_clause(where)
        values = list(updates.values()) + where_values
        query = f"UPDATE {self.table} SET {set_clause} WHERE {where_clause};"
        return query, values

    def _build_where_clause(self, filters: Dict[str, Any]) -> Tuple[str, List[Any]]:
        clause = " AND ".join([f"{key} = %s" for key in filters])
        values = list(filters.values())
        return clause, values
