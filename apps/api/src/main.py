from __future__ import annotations

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from editor_permissions import (
    EditorPermissionsMiddleware,
    get_editor_permissions_config,
)
from observability import (
    TraceIdMiddleware,
    configure_logging,
    register_exception_handlers,
)
from rate_limit import RateLimitMiddleware, create_redis_client
from routers.attribution import router as attribution_router
from routers.analytics import router as analytics_router
from routers.catalog import router as catalog_router
from routers.errors import router as errors_router
from routers.effects import router as effects_router
from routers.ingest import router as ingest_router
from routers.legends import router as legends_router
from routers.local_data import router as local_data_router
from routers.products import router as products_router
from routers.risk import router as risk_router
from routers.tiles import router as tiles_router
from routers.sample import router as sample_router
from routers.vector import router as vector_router
from routers.volume import router as volume_router


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(debug=settings.api.debug)

    app = FastAPI(title="Digital Earth API", debug=settings.api.debug)

    redis_client = create_redis_client(settings.redis.url)
    app.state.redis_client = redis_client

    app.add_middleware(
        RateLimitMiddleware,
        config=settings.api.rate_limit,
        redis_client=redis_client,
    )

    app.add_middleware(
        EditorPermissionsMiddleware,
        config=settings.api.rate_limit,
        redis_client=redis_client,
        permissions=get_editor_permissions_config(),
    )

    app.add_middleware(TraceIdMiddleware)

    @app.on_event("shutdown")
    async def _close_redis_client() -> None:
        await redis_client.close()

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
    api_v1.include_router(analytics_router)
    api_v1.include_router(attribution_router)
    api_v1.include_router(catalog_router)
    api_v1.include_router(local_data_router)
    api_v1.include_router(ingest_router)
    api_v1.include_router(errors_router)
    api_v1.include_router(risk_router)
    api_v1.include_router(tiles_router)
    api_v1.include_router(sample_router)
    api_v1.include_router(products_router)
    api_v1.include_router(vector_router)
    api_v1.include_router(legends_router)
    api_v1.include_router(volume_router)
    app.include_router(api_v1)

    return app


app = create_app()
