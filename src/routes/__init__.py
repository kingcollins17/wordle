from .auth import auth_router
from .game import game_router
from .leaderboards import lb_router
from .store import store_router

from .words import words_router
from .rewards import rewards_router

__all__ = [
    "auth_router",
    "game_router",
    "lb_router",
    "store_router",
    "words_router",
    "rewards_router",
]
