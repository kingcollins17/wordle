from fastapi import APIRouter, Depends, HTTPException, status
from typing import Optional, List
from pydantic import BaseModel, Field

from src.core.api_tags import APITags
from src.core import BaseResponse
from src.models.word import Word
from src.repositories.word_repository import WordRepository, get_word_repository

words_router = APIRouter(prefix="/words", tags=[APITags.WORDS])

class CreateWordRequest(BaseModel):
    word: str = Field(..., max_length=255)
    meaning: Optional[str] = None
    is_active: bool = False
    word_length: Optional[int] = None # Calculated if not provided

class UpdateWordRequest(BaseModel):
    word: Optional[str] = Field(None, max_length=255)
    meaning: Optional[str] = None
    is_active: Optional[bool] = None
    word_length: Optional[int] = None

@words_router.post("/", response_model=BaseResponse, status_code=status.HTTP_201_CREATED)
async def create_word(
    request: CreateWordRequest,
    repo: WordRepository = Depends(get_word_repository)
):
    try:
        # Check if word exists
        existing = await repo.get_word_by_text(request.word)
        if existing:
            raise HTTPException(status_code=400, detail="Word already exists")

        word_len = request.word_length if request.word_length else len(request.word)
        
        word_data = {
            "word": request.word,
            "meaning": request.meaning,
            "is_active": request.is_active,
            "word_length": word_len
        }

        word_id = await repo.create_word(word_data)

        return BaseResponse(
            success=True,
            message="Word created successfully",
            data={"id": word_id, **word_data}
        )
    except HTTPException:
        raise
    except Exception as e:
        if "Duplicate entry" in str(e):
            raise HTTPException(status_code=400, detail="Word already exists")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")

@words_router.get("/{word_id}", response_model=BaseResponse)
async def get_word(
    word_id: int,
    repo: WordRepository = Depends(get_word_repository)
):
    try:
        word = await repo.get_word_by_id(word_id)
        if not word:
            raise HTTPException(status_code=404, detail="Word not found")
        
        return BaseResponse(
            success=True,
            message="Word fetched successfully",
            data=Word(**word)
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")

@words_router.put("/{word_id}", response_model=BaseResponse)
async def update_word(
    word_id: int,
    request: UpdateWordRequest,
    repo: WordRepository = Depends(get_word_repository)
):
    try:
        updates = request.model_dump(exclude_none=True)
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")

        # If updating word text, recalculate length if not provided
        if "word" in updates and "word_length" not in updates:
            updates["word_length"] = len(updates["word"])

        affected = await repo.update_word(word_id, updates)
        if affected == 0:
            # Check if it exists
            if not await repo.get_word_by_id(word_id):
                raise HTTPException(status_code=404, detail="Word not found")
            # If exists but no change, success

        return BaseResponse(
            success=True,
            message="Word updated successfully",
            data={"id": word_id, "updates": updates}
        )
    except HTTPException:
        raise
    except Exception as e:
        if "Duplicate entry" in str(e):
            raise HTTPException(status_code=400, detail="Word already exists")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")

@words_router.delete("/{word_id}", response_model=BaseResponse)
async def delete_word(
    word_id: int,
    repo: WordRepository = Depends(get_word_repository)
):
    try:
        affected = await repo.delete_word(word_id)
        if affected == 0:
            if not await repo.get_word_by_id(word_id):
                 raise HTTPException(status_code=404, detail="Word not found")

        return BaseResponse(
            success=True,
            message="Word deleted successfully",
            data={"id": word_id}
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")

@words_router.get("/", response_model=BaseResponse[List[Word]])
async def list_words(
    page: int = 1,
    per_page: int = 1000,
    active_only: Optional[bool] = True,
    word_length: Optional[int] = None,
    repo: WordRepository = Depends(get_word_repository)
):
    try:
        limit = per_page
        offset = (page - 1) * per_page
        
        filters = {}
        if active_only is not None:
            filters["is_active"] = active_only
        
        if word_length is not None:
            filters["word_length"] = word_length

        words = await repo.list_words(filters=filters, limit=limit, offset=offset)

        return BaseResponse(
            success=True,
            message="Words list fetched successfully",
            data=words
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")
