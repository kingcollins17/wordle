from enum import Enum
import logging
from typing import List, Literal, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.core.api_tags import APITags
from src.core.base_response import BaseResponse
from src.core.models.user import User
from src.core.repository import Repository, GetRepository
from src.core.dependencies import get_current_user

logger = logging.getLogger(__name__)

store_router = APIRouter(prefix="/store", tags=[APITags.STORE])

coin_pack_500 = "coin_pack_500"
coin_pack_1500 = "coin_pack_1500"
coin_pack_5000 = "coin_pack_5000"
coin_pack_15000 = "coin_pack_15000"

product_coins = {
    coin_pack_500: 500,
    coin_pack_1500: 1500,
    coin_pack_5000: 5000,
    coin_pack_15000: 15000,
}

powerup_fish_out = "fish_out"
powerup_word_meaning = "word_meaning"
powerup_reveal_letter = "reveal_letter"

product_powerups = {
    powerup_fish_out: {"price": 150, "quantity": 1},
    powerup_word_meaning: {"price": 200, "quantity": 1},
    powerup_reveal_letter: {"price": 250, "quantity": 1},
    "fish_out_pack_10": {"price": 1200, "quantity": 10},
    "word_meaning_pack_10": {"price": 1600, "quantity": 10},
    "reveal_letter_pack_10": {"price": 2000, "quantity": 10},
    "fish_out_pack_25": {"price": 2800, "quantity": 25},
    "word_meaning_pack_25": {"price": 4000, "quantity": 25},
    "reveal_letter_pack_25": {"price": 5000, "quantity": 25},
}


@store_router.post("/purchase/{product_id}", response_model=BaseResponse)
async def purchase_item(
    product_id: Literal[
        "coin_pack_1500", "coin_pack_500", "coin_pack_5000", "coin_pack_15000"
    ],
    purchase_id: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    repo: Repository[User] = Depends(GetRepository(User)),
) -> BaseResponse[dict]:
    try:
        if product_id not in product_coins:
            raise HTTPException(status_code=400, detail="Invalid product ID")

        coins_to_add = product_coins[product_id]
        updated_user = await repo.update(current_user, {"coins": current_user.coins + coins_to_add})

        logger.info(f"Successful purchase by {current_user.id}: {product_id}")
        return BaseResponse(
            success=True,
            message="Product purchased successfully",
            data={"purchased": True, "coins": updated_user.coins},
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error during purchase: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500, detail="An unexpected error occurred during purchase"
        )


class PowerupResponse(BaseModel):
    id: str
    price: int
    quantity: int


@store_router.get("/powerups", response_model=BaseResponse[List[PowerupResponse]])
async def get_powerups_store() -> BaseResponse[List[PowerupResponse]]:
    powerups = [
        PowerupResponse(id=pid, price=details["price"], quantity=details["quantity"])
        for pid, details in product_powerups.items()
    ]
    return BaseResponse(success=True, message="Powerups retrieved", data=powerups)


@store_router.post("/purchase-powerup/{product_id}", response_model=BaseResponse)
async def purchase_powerup(
    product_id: str,
    current_user: User = Depends(get_current_user),
    repo: Repository[User] = Depends(GetRepository(User)),
) -> BaseResponse[dict]:
    try:
        if product_id not in product_powerups:
            raise HTTPException(status_code=400, detail="Invalid power-up ID")

        powerup = product_powerups[product_id]
        price, quantity = powerup["price"], powerup["quantity"]

        if current_user.coins < price:
            raise HTTPException(status_code=400, detail="Not enough coins")

        if product_id.startswith("fish_out"):
            powerup_field = "fish_out"
        elif product_id.startswith("word_meaning"):
            powerup_field = "word_meaning"
        elif product_id.startswith("reveal_letter"):
            powerup_field = "reveal_letter"
        else:
            raise HTTPException(status_code=400, detail="Invalid power-up type")

        new_coins = current_user.coins - price
        current_count = getattr(current_user, powerup_field, 0)
        new_powerup_count = current_count + quantity

        await repo.update(
            current_user,
            {
                "coins": new_coins,
                powerup_field: new_powerup_count,
            },
        )

        return BaseResponse(
            success=True,
            message="Power-up purchased successfully",
            data={
                "powerup": product_id,
                "quantity_added": quantity,
                "remaining_coins": new_coins,
                "new_total": new_powerup_count,
            },
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Unexpected error during power-up purchase: {str(e)}", exc_info=True
        )
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred during power-up purchase",
        )
