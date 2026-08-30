from typing import Optional, Dict, Any, List, Union
from pydantic import BaseModel, Field


class QueryOptions(BaseModel):
    """
    Options object for querying models with Repository[T].
    Supports equality filters, SQLAlchemy binary expressions (where),
    ordering, limit, and offset.
    """

    filters: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Equality filters mapping column field name to value",
    )
    where: Optional[List[Any]] = Field(
        default=None,
        description="SQLAlchemy binary expressions for complex query conditions",
    )
    order_by: Optional[Union[str, List[Union[str, Any]], Any]] = Field(
        default=None,
        description="Column name or list of column names / order expressions",
    )
    ascending: bool = Field(
        default=True,
        description="Sort direction if order_by is column name string(s)",
    )
    limit: Optional[int] = Field(
        default=None,
        description="Maximum number of records to return",
    )
    offset: Optional[int] = Field(
        default=None,
        description="Number of records to skip",
    )

    class Config:
        arbitrary_types_allowed = True
