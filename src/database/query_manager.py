from typing import List, Dict, Any, Optional, Tuple, Union
import logging

logger = logging.getLogger(__name__)


class QueryManager:
    def __init__(self, table: str):
        self.table = table

    def select_one(self, where: Dict[str, Any]) -> Tuple[str, List[Any]]:
        where_clause, values = self._build_where_clause(where)
        query = f"SELECT * FROM {self.table} WHERE {where_clause} LIMIT 1;"
        return query, values

    def select_many(
        self,
        where: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
        offset: Optional[int] = None,
        order_by: Optional[str] = None,
        ascending: bool = True,
    ) -> Tuple[str, List[Any]]:
        """Build a SELECT query for multiple records with pagination and sorting."""
        where_clause, values = self._build_where_clause(where) if where else ("1", [])

        query = f"SELECT * FROM {self.table} WHERE {where_clause}"

        if order_by:
            direction = "ASC" if ascending else "DESC"
            query += f" ORDER BY {order_by} {direction}"

        if limit is not None:
            query += f" LIMIT {limit}"
            if offset is not None:
                query += f" OFFSET {offset}"

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

    # -------------------------
    # DELETE METHODS
    # -------------------------

    def delete(self, where: Dict[str, Any]) -> Tuple[str, List[Any]]:
        """
        Build a DELETE query with WHERE conditions.

        Args:
            where: Dictionary of conditions for the WHERE clause

        Returns:
            Tuple of (query, parameters)

        Raises:
            ValueError: If where conditions are empty (to prevent accidental full table deletion)
        """
        if not where:
            raise ValueError(
                "DELETE operations require WHERE conditions to prevent accidental data loss"
            )

        where_clause, values = self._build_where_clause(where)
        query = f"DELETE FROM {self.table} WHERE {where_clause};"
        return query, values

    def delete_by_id(self, record_id: Union[int, str]) -> Tuple[str, List[Any]]:
        """
        Build a DELETE query by ID (assumes primary key is 'id').

        Args:
            record_id: The ID of the record to delete

        Returns:
            Tuple of (query, parameters)
        """
        return self.delete({"id": record_id})

    def delete_by_ids(self, record_ids: List[Union[int, str]]) -> Tuple[str, List[Any]]:
        """
        Build a DELETE query for multiple records by their IDs.

        Args:
            record_ids: List of IDs to delete

        Returns:
            Tuple of (query, parameters)

        Raises:
            ValueError: If record_ids list is empty
        """
        if not record_ids:
            raise ValueError("record_ids cannot be empty")

        placeholders = ", ".join(["%s"] * len(record_ids))
        query = f"DELETE FROM {self.table} WHERE id IN ({placeholders});"
        return query, list(record_ids)

    def delete_with_limit(
        self, where: Dict[str, Any], limit: int, order_by: Optional[str] = None
    ) -> Tuple[str, List[Any]]:
        """
        Build a DELETE query with LIMIT clause (MySQL specific).
        Useful for deleting a specific number of records.

        Args:
            where: Dictionary of conditions for the WHERE clause
            limit: Maximum number of records to delete
            order_by: Optional column to order by before limiting

        Returns:
            Tuple of (query, parameters)

        Note:
            This is MySQL-specific syntax. Other databases may not support LIMIT in DELETE.
        """
        if not where:
            raise ValueError("DELETE operations require WHERE conditions")

        where_clause, values = self._build_where_clause(where)
        query = f"DELETE FROM {self.table} WHERE {where_clause}"

        if order_by:
            query += f" ORDER BY {order_by}"

        query += f" LIMIT {limit};"
        return query, values

    def delete_older_than(
        self,
        date_column: str,
        days: int,
        additional_where: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, List[Any]]:
        """
        Build a DELETE query for records older than specified days.

        Args:
            date_column: Name of the date/datetime column to check
            days: Number of days to look back
            additional_where: Additional WHERE conditions

        Returns:
            Tuple of (query, parameters)
        """
        base_condition = f"{date_column} < DATE_SUB(NOW(), INTERVAL %s DAY)"
        values = [days]

        if additional_where:
            additional_clause, additional_values = self._build_where_clause(
                additional_where
            )
            where_clause = f"({base_condition}) AND ({additional_clause})"
            values.extend(additional_values)
        else:
            where_clause = base_condition

        query = f"DELETE FROM {self.table} WHERE {where_clause};"
        return query, values

    def truncate_table(self) -> Tuple[str, List[Any]]:
        """
        Build a TRUNCATE query to remove all records and reset auto-increment.

        Returns:
            Tuple of (query, empty parameters list)

        Warning:
            This operation cannot be undone and removes ALL data from the table.
        """
        logger.warning(f"TRUNCATE operation requested for table: {self.table}")
        query = f"TRUNCATE TABLE {self.table};"
        return query, []

    def delete_all_unsafe(self) -> Tuple[str, List[Any]]:
        """
        Build a DELETE query to remove all records (keeping table structure).

        Returns:
            Tuple of (query, parameters)

        Warning:
            This operation removes ALL data from the table. Use with extreme caution.
            Consider using truncate_table() instead for better performance.
        """
        logger.warning(f"DELETE ALL operation requested for table: {self.table}")
        query = f"DELETE FROM {self.table};"
        return query, []

    # -------------------------
    # ENHANCED WHERE CLAUSE BUILDERS
    # -------------------------

    def _build_where_clause(self, filters: Dict[str, Any]) -> Tuple[str, List[Any]]:
        """Build basic WHERE clause with equality conditions."""
        clause = " AND ".join([f"{key} = %s" for key in filters])
        values = list(filters.values())
        return clause, values

    def _build_advanced_where_clause(
        self, filters: Dict[str, Any], operators: Optional[Dict[str, str]] = None
    ) -> Tuple[str, List[Any]]:
        """
        Build advanced WHERE clause with custom operators.

        Args:
            filters: Dictionary of column: value pairs
            operators: Dictionary of column: operator pairs (e.g., {'age': '>', 'name': 'LIKE'})

        Returns:
            Tuple of (where_clause, parameters)
        """
        if not filters:
            return "1", []

        operators = operators or {}
        conditions = []
        values = []

        for key, value in filters.items():
            operator = operators.get(key, "=")

            if operator.upper() == "IN" and isinstance(value, (list, tuple)):
                placeholders = ", ".join(["%s"] * len(value))
                conditions.append(f"{key} IN ({placeholders})")
                values.extend(value)
            elif (
                operator.upper() == "BETWEEN"
                and isinstance(value, (list, tuple))
                and len(value) == 2
            ):
                conditions.append(f"{key} BETWEEN %s AND %s")
                values.extend(value)
            elif operator.upper() == "LIKE":
                conditions.append(f"{key} LIKE %s")
                values.append(f"%{value}%")
            else:
                conditions.append(f"{key} {operator} %s")
                values.append(value)

        clause = " AND ".join(conditions)
        return clause, values
