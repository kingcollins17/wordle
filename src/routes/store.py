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


# --- Add below coin packs definition ---

powerup_fish_out = "fish_out"
powerup_ai_meaning = "ai_meaning"
powerup_reveal_letter = "reveal_letter"

# Single purchase options
product_powerups = {
    powerup_fish_out: {"price": 150, "quantity": 1},
    powerup_ai_meaning: {"price": 200, "quantity": 1},
    powerup_reveal_letter: {"price": 250, "quantity": 1},
    # Packs
    "fish_out_pack_10": {"price": 1200, "quantity": 10},
    "ai_meaning_pack_10": {"price": 1600, "quantity": 10},
    "reveal_letter_pack_10": {"price": 2000, "quantity": 10},
    "fish_out_pack_25": {"price": 2800, "quantity": 25},
    "ai_meaning_pack_25": {"price": 4000, "quantity": 25},
    "reveal_letter_pack_25": {"price": 5000, "quantity": 25},
}


@store_router.post("/purchase/{product_id}", response_model=BaseResponse)
async def purchase_item(
    product_id: Literal[
        "coin_pack_1500", "coin_pack_500", "coin_pack_5000", "coin_pack_15000"
    ],
    purchase_id: Optional[str] = None,
    current_user: WordleUser = Depends(get_current_user),
    repo: UserRepository = Depends(get_user_repository),
) -> BaseResponse[dict]:

    try:

        def validate_purchase_id(purchase_id) -> bool:
            return True

        if product_id not in product_coins:
            raise HTTPException(status_code=400, detail="Invalid product ID")
        if purchase_id and not validate_purchase_id(purchase_id):
            raise HTTPException(status_code=400, detail="Invalid purchase ID")
        coins_to_add = product_coins[product_id]
        await repo.update_user_by_device_id(
            device_id=current_user.device_id,
            updates={"coins": current_user.coins + coins_to_add},
        )
        logger.info(f"Successful purchase by {current_user.device_id}: {product_id}")
        return BaseResponse(
            success=True,
            message="Product purchased successfully",
            data={"purchased": True},
        )

    except HTTPException:
        raise  # Re-raise already handled HTTP exceptions
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
    """
    Returns available powerups and their prices (including packs).
    """
    powerups = [
        PowerupResponse(id=pid, price=details["price"], quantity=details["quantity"])
        for pid, details in product_powerups.items()
    ]
    return BaseResponse(success=True, message="Powerups retrieved", data=powerups)


@store_router.post("/purchase-powerup/{product_id}", response_model=BaseResponse)
async def purchase_powerup(
    product_id: str,
    current_user: WordleUser = Depends(get_current_user),
    repo: UserRepository = Depends(get_user_repository),
) -> BaseResponse[dict]:
    """
    Endpoint to purchase a power-up or pack.
    Deducts coins and increments the user's chosen power-up count.
    """

    try:
        if product_id not in product_powerups:
            raise HTTPException(status_code=400, detail="Invalid power-up ID")

        powerup = product_powerups[product_id]
        price, quantity = powerup["price"], powerup["quantity"]

        # Ensure user has enough coins
        if current_user.coins < price:
            raise HTTPException(status_code=400, detail="Not enough coins")

        # Determine which power-up to increment
        if product_id.startswith("fish_out"):
            powerup_field = "fish_out"
        elif product_id.startswith("ai_meaning"):
            powerup_field = "ai_meaning"
        elif product_id.startswith("reveal_letter"):
            powerup_field = "reveal_letter"
        else:
            raise HTTPException(status_code=400, detail="Invalid power-up type")

        # Update user balance and power-up
        new_coins = current_user.coins - price
        new_powerup_count = getattr(current_user, powerup_field) + quantity

        await repo.update_user_by_device_id(
            device_id=current_user.device_id,
            updates={
                "coins": new_coins,
                powerup_field: new_powerup_count,
            },
        )

        logger.info(
            f"User {current_user.device_id} purchased {product_id} "
            f"(-{price} coins, +{quantity} {powerup_field})"
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
