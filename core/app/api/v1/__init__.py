"""API v1 routers."""

from fastapi import APIRouter

from app.api.v1.recognize import router as recognize_router

api_v1_router = APIRouter(prefix="/v1")
api_v1_router.include_router(recognize_router)

__all__ = ["api_v1_router"]
