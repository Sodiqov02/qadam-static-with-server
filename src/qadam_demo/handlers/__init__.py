"""Bot handlers package"""
from aiogram import Router
from .start import router as start_router
from .admin import router as admin_router
from .menu import router as menu_router

__all__ = ["setup_routers"]

def setup_routers() -> Router:
    """Setup all routers for the bot"""
    root = Router(name=__name__)
    root.include_router(start_router)
    root.include_router(admin_router)
    root.include_router(menu_router)
    return root