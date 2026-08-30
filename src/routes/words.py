from fastapi import APIRouter, Depends, HTTPException, status
from typing import Optional, List
from pydantic import BaseModel, Field

from src.core.api_tags import APITags
from src.core import BaseResponse, QueryOptions
from src.core.models.word import Word
from src.core.repository import Repository, GetRepository
from src.core.services.word_service import WordService, get_word_service

words_router = APIRouter(prefix="/words", tags=[APITags.WORDS])


class CreateWordRequest(BaseModel):
    word: str = Field(..., max_length=255)
    meaning: Optional[str] = None
    is_active: bool = False
    word_length: Optional[int] = None  # Calculated if not provided


class UpdateWordRequest(BaseModel):
    word: Optional[str] = Field(None, max_length=255)
    meaning: Optional[str] = None
    is_active: Optional[bool] = None
    word_length: Optional[int] = None


@words_router.post("/", response_model=BaseResponse, status_code=status.HTTP_201_CREATED)
async def create_word(
    request: CreateWordRequest,
    repo: Repository[Word] = Depends(GetRepository(Word)),
):
    try:
        existing = await repo.get(options=QueryOptions(filters={"word": request.word}))
        if existing:
            raise HTTPException(status_code=400, detail="Word already exists")

        word_len = request.word_length if request.word_length else len(request.word)

        word_entity = Word(
            word=request.word,
            meaning=request.meaning,
            is_active=request.is_active,
            word_length=word_len,
        )

        created_word = await repo.add(word_entity)

        return BaseResponse(
            success=True,
            message="Word created successfully",
            data=created_word,
        )
    except HTTPException:
        raise
    except Exception as e:
        if "Duplicate entry" in str(e):
            raise HTTPException(status_code=400, detail="Word already exists")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")


@words_router.get("/random", response_model=BaseResponse)
async def get_random_word(
    length: int = 4,
    word_service: WordService = Depends(get_word_service),
):
    try:
        word = await word_service.get_random(length=length)
        if not word:
            raise HTTPException(status_code=404, detail="No matching word found")

        return BaseResponse(
            success=True,
            message="Random word fetched successfully",
            data=word,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")


@words_router.get("/{word_id}", response_model=BaseResponse)
async def get_word(
    word_id: str,
    repo: Repository[Word] = Depends(GetRepository(Word)),
):
    try:
        word = await repo.get(id=word_id)
        if not word:
            raise HTTPException(status_code=404, detail="Word not found")

        return BaseResponse(
            success=True,
            message="Word fetched successfully",
            data=word,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")


@words_router.put("/{word_id}", response_model=BaseResponse)
async def update_word(
    word_id: str,
    request: UpdateWordRequest,
    repo: Repository[Word] = Depends(GetRepository(Word)),
):
    try:
        word = await repo.get(id=word_id)
        if not word:
            raise HTTPException(status_code=404, detail="Word not found")

        updates = request.model_dump(exclude_none=True)
        if not updates:
            raise HTTPException(status_code=400, detail="No fields to update")

        if "word" in updates and "word_length" not in updates:
            updates["word_length"] = len(updates["word"])

        updated_word = await repo.update(word, updates)

        return BaseResponse(
            success=True,
            message="Word updated successfully",
            data=updated_word,
        )
    except HTTPException:
        raise
    except Exception as e:
        if "Duplicate entry" in str(e):
            raise HTTPException(status_code=400, detail="Word already exists")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")


@words_router.delete("/{word_id}", response_model=BaseResponse)
async def delete_word(
    word_id: str,
    repo: Repository[Word] = Depends(GetRepository(Word)),
):
    try:
        word = await repo.get(id=word_id)
        if not word:
            raise HTTPException(status_code=404, detail="Word not found")

        await repo.delete(word)

        return BaseResponse(
            success=True,
            message="Word deleted successfully",
            data={"id": word_id},
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
    repo: Repository[Word] = Depends(GetRepository(Word)),
):
    try:
        limit = per_page
        offset = (page - 1) * per_page

        filters = {}
        if active_only is not None:
            filters["is_active"] = active_only

        if word_length is not None:
            filters["word_length"] = word_length

        options = QueryOptions(filters=filters, limit=limit, offset=offset)
        words = await repo.get_many(options=options)

        return BaseResponse(
            success=True,
            message="Words list fetched successfully",
            data=words,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")
