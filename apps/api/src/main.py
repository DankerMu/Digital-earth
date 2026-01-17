from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from observability import (
    TraceIdMiddleware,
    configure_logging,
    register_exception_handlers,
)
from routers.attribution import router as attribution_router
from routers.effects import router as effects_router
from routers.local_data import router as local_data_router


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(debug=settings.api.debug)

    app = FastAPI(title="Digital Earth API", debug=settings.api.debug)

    # Add trace_id middleware first
    app.add_middleware(TraceIdMiddleware)

    if settings.api.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.api.cors_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    register_exception_handlers(app)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    api_v1 = APIRouter(prefix="/api/v1")
    api_v1.include_router(effects_router)
    api_v1.include_router(attribution_router)
    api_v1.include_router(local_data_router)
    app.include_router(api_v1)

    return app


app = create_app()
