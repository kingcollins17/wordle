from enum import Enum
import logging
from fastapi import APIRouter, Depends, HTTPException
from typing import List

from fastapi import APIRouter
from pydantic import BaseModel
from src.core.api_tags import APITags
from src.core.base_response import BaseResponse
from src.models import *
from src.repositories import *


logger = logging.getLogger(__name__)


class StoreItem(BaseModel):
    type: PowerUpType
    store_product_id: str
    name: str
    price: int
    amount: int  # How many uses/power-ups come with this purchase


POWERUP_STORE_ITEMS = [
    StoreItem(
        type=PowerUpType.FISH_OUT,
        store_product_id="",
        name="Fisherman's Net",
        price=150,
        amount=3,  # Removes 3 letters
    ),
    StoreItem(
        type=PowerUpType.REVEAL_LETTER,
        store_product_id="",
        name="X-Ray Glasses",
        price=250,
        amount=1,  # Reveals 1 letter
    ),
    StoreItem(
        type=PowerUpType.AI_MEANING,
        name="Word Scholar",
        store_product_id="",
        price=400,
        amount=1,  # Provides 1 meaning
    ),
]


def get_store_items() -> list[StoreItem]:
    return POWERUP_STORE_ITEMS.copy()


store_router = APIRouter(prefix="/store", tags=[APITags.STORE])

from fastapi import APIRouter, Depends, HTTPException
from typing import List

store_router = APIRouter(prefix="/store", tags=[APITags.STORE])


@store_router.get("/items", response_model=List[StoreItem])
async def store_items():
    """Get all available store items"""
    return get_store_items()


@store_router.post("/purchase/{item_index}", response_model=BaseResponse)
async def purchase_item(
    item_index: int,
    current_user: WordleUser = Depends(get_current_user),
    repo: UserRepository = Depends(get_user_repository),
) -> BaseResponse[dict]:
    """
    Purchase an item from the store

    Args:
        item_index: Index of the item in the store list
        current_user: Authenticated user making the purchase
        repo: User repository for database operations

    Returns:
        BaseResponse with success/error message
    """
    try:
        logger.info(
            f"Purchase attempt by user {current_user.device_id} for item {item_index}"
        )

        items = get_store_items()

        # Validate item index
        if item_index < 0 or item_index >= len(items):
            error_msg = f"Invalid item index {item_index}"
            logger.warning(error_msg)
            raise HTTPException(status_code=404, detail="Item not found")

        item = items[item_index]

        # Check user balance
        if current_user.coins < item.price:
            error_msg = f"Insufficient coins for user {current_user.device_id}"
            logger.error(error_msg)
            raise HTTPException(
                status_code=400, detail="Not enough coins for this purchase"
            )

        # Prepare update data
        updates = {
            "coins": current_user.coins - item.price,
            item.type.value: current_user.model_dump().get(item.type.value, 0)
            + item.amount,
        }

        # Update user in database
        try:
            affected_rows = await repo.update_user_by_device_id(
                device_id=current_user.device_id, updates=updates
            )
            if affected_rows == 0:
                raise Exception("No rows were updated")
        except Exception as db_error:
            logger.error(
                f"Database update failed for user {current_user.device_id}: {str(db_error)}"
            )
            raise HTTPException(status_code=500, detail="Failed to process purchase")

        logger.info(f"Successful purchase by {current_user.device_id}: {item.name}")
        return BaseResponse(
            success=True,
            message="Item purchased successfully",
            data={"purchased": True},
        )

    except HTTPException:
        raise  # Re-raise already handled HTTP exceptions
    except Exception as e:
        logger.error(f"Unexpected error during purchase: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500, detail="An unexpected error occurred during purchase"
        )
