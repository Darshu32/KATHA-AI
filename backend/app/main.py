"""KATHA AI FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db import AuditEvent  # noqa: F401  (registers table on Base.metadata)
from app.middleware import RateLimitMiddleware
from app.models import architecture  # noqa: F401
from app.models import orm  # noqa: F401
from app.models import pricing  # noqa: F401  (Stage 1 pricing tables)
from app.models import standards as standard_models  # noqa: F401  (Stage 3B building_standards table)
from app.models import suggestions as suggestion_models  # noqa: F401  (Stage 3F suggestions table)
from app.models import themes as theme_models  # noqa: F401  (Stage 3A themes table)
from app.models.schemas import ErrorResponse, ErrorDetail
from app.observability.error_envelope import install_error_handlers
from app.observability.logging import configure_logging
from app.observability.otel import install as install_otel
from app.observability.request_id import RequestIdMiddleware
from app.routes import all_routers

settings = get_settings()
configure_logging(debug=settings.debug)
settings.assert_production_safe()


@asynccontextmanager
async def lifespan(_: FastAPI):
    """App lifespan hook.

    Schema is owned by Alembic (see ``backend/alembic/versions/``).
    Run migrations explicitly before starting the app::

        alembic upgrade head

    The previous ``Base.metadata.create_all`` bootstrap was removed in
    Stage 0 — relying on it caused silent schema drift and broke
    audit/versioning guarantees.
    """
    yield


app = FastAPI(
    title="KATHA AI API",
    version="0.2.0",
    description="Backend for the KATHA AI architecture & interior design platform.",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(RequestIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Stage 13 — sliding-window rate limiter. Soft-fails when Redis is
# unreachable so a limiter outage never becomes an API outage.
app.add_middleware(
    RateLimitMiddleware,
    redis_url=settings.redis_url,
)

for router in all_routers:
    app.include_router(router, prefix="/api/v1")


# Stage 13 — canonical error envelope. Replaces the inline handlers
# that lived here through Stage 0–12; same shape, but now driven by
# ``ErrorCode`` enum so client integrations get stable codes.
install_error_handlers(app)


# Stage 13 — OpenTelemetry. No-op when ``OTEL_EXPORTER_OTLP_ENDPOINT``
# is unset (the default). When configured, every request becomes a
# span exported via OTLP/HTTP — vendor-agnostic.
install_otel(app)


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok", "version": "0.2.0"}
