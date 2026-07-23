"""FastAPI entrypoint for EnPu core."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.v1 import api_v1_router
from app.config import get_settings
from app.schemas.recognize import HealthResponse


def create_app() -> FastAPI:
    settings = get_settings()

    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version or __version__,
        description=(
            "EnPu recognition core — Chinese worship jianpu OMR service. "
            "Phase 0: /health + mock /v1/recognize (#2). Real OCR in #3."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.get(
        "/health",
        response_model=HealthResponse,
        tags=["health"],
        summary="Health check",
    )
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            version=settings.app_version or __version__,
        )

    application.include_router(api_v1_router)
    return application


app = create_app()
