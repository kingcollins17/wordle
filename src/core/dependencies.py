from fastapi import Depends, Header, HTTPException
from src.core.models import User
from src.core import GetRepository

from typing import Optional
from src.core import Repository

async def get_current_user(
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    user_id: Optional[str] = Header(None, alias="user-id"),
    repo: Repository[User] = Depends(GetRepository(User)),
) -> User:
    uid = x_user_id or user_id
    if not uid:
        raise HTTPException(status_code=401, detail="User ID header required (X-User-ID or user-id)")
    user = await repo.get(id=uid)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user



async def get_optional_user(
    x_user_id: Optional[str] = Header(None, alias="X-User-ID"),
    user_id: Optional[str] = Header(None, alias="user-id"),
    repo: Repository[User] = Depends(GetRepository(User)),
) -> Optional[User]:
    uid = x_user_id or user_id
    if not uid:
        return None
    return await repo.get(id=uid)
