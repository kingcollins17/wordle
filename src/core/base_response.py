from pydantic import BaseModel
from typing import Optional, Any, TypeVar, Generic

T = TypeVar("T")


class BaseResponse(BaseModel, Generic[T]):
    success: bool = True
    message: Optional[str] = None
    data: Optional[T] = None
