from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import Optional, List, Dict
from pydantic import BaseModel, Field
from sqlmodel import col

from src.core.api_tags import APITags
from src.core import BaseResponse, QueryOptions
from src.core.models.word import Word
from src.core.repository import Repository, GetRepository
from src.core.services.word_service import WordService, get_word_service

words_router = APIRouter(prefix="/words", tags=[APITags.WORDS])


class WordItem(BaseModel):
    word: str = Field(..., max_length=255)
    meaning: Optional[str] = None
    is_active: bool = False
    word_length: Optional[int] = None  # Calculated if not provided


class CreateWordRequest(BaseModel):
    words: Optional[List[WordItem]] = Field(None, description="List of word objects for bulk creation")
    word: Optional[str] = Field(None, max_length=255, description="Single word string for single creation")
    meaning: Optional[str] = None
    is_active: bool = False
    word_length: Optional[int] = None


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
        raw_items: List[WordItem] = []
        if request.words:
            raw_items.extend(request.words)
        if request.word:
            raw_items.append(
                WordItem(
                    word=request.word,
                    meaning=request.meaning,
                    is_active=request.is_active,
                    word_length=request.word_length,
                )
            )

        if not raw_items:
            raise HTTPException(
                status_code=400,
                detail="Either 'words' list or 'word' field must be provided.",
            )

        # Clean, convert to uppercase, and deduplicate items in request
        items_by_upper: Dict[str, WordItem] = {}
        for item in raw_items:
            cleaned_word = item.word.strip().upper()
            if not cleaned_word:
                continue
            if cleaned_word not in items_by_upper:
                items_by_upper[cleaned_word] = item

        if not items_by_upper:
            raise HTTPException(status_code=400, detail="No valid non-empty words provided.")

        words_to_check = list(items_by_upper.keys())

        # Bulk query existing words in DB to avoid N+1 queries
        existing_records = await repo.get_many(
            options=QueryOptions(where=[col(Word.word).in_(words_to_check)])
        )
        existing_words_set = {w.word.upper() for w in existing_records}

        new_items = [
            item for upper_w, item in items_by_upper.items()
            if upper_w not in existing_words_set
        ]

        if not new_items:
            if len(items_by_upper) == 1:
                raise HTTPException(status_code=400, detail="Word already exists")
            return BaseResponse(
                success=True,
                message="All provided words already exist in the database.",
                data=[],
            )

        entities_to_create = []
        for item in new_items:
            upper_word = item.word.strip().upper()
            word_len = item.word_length if item.word_length else len(upper_word)
            entities_to_create.append(
                Word(
                    word=upper_word,
                    meaning=item.meaning,
                    is_active=item.is_active,
                    word_length=word_len,
                )
            )

        # Fast bulk insert using optimized add_many (refresh=False)
        created_words = await repo.add_many(entities_to_create, refresh=False)

        if len(raw_items) == 1 and len(created_words) == 1:
            return BaseResponse(
                success=True,
                message="Word created successfully",
                data=created_words[0],
            )

        return BaseResponse(
            success=True,
            message=f"Successfully created {len(created_words)} word(s)",
            data=created_words,
        )

    except HTTPException:
        raise
    except Exception as e:
        if "Duplicate entry" in str(e):
            raise HTTPException(status_code=400, detail="One or more words already exist")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")


@words_router.get("/random", response_model=BaseResponse[List[Word]])
async def get_random_word(
    length: Optional[int] = Query(4, ge=1),
    count: int = Query(1, ge=1, le=100),
    word_service: WordService = Depends(get_word_service),
):
    try:
        words = await word_service.get_random(length=length, count=count)
        if not words:
            raise HTTPException(status_code=404, detail="No matching words found")

        return BaseResponse(
            success=True,
            message="Random word(s) fetched successfully",
            data=words,
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
