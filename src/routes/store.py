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
