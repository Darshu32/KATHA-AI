"""KATHA AI FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import Base, engine
from app.models import architecture  # noqa: F401
from app.models import orm  # noqa: F401
from app.models.schemas import ErrorResponse, ErrorDetail
from app.routes import all_routers

settings = get_settings()

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Dev-friendly bootstrap until Alembic migrations are added.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(
    title="KATHA AI API",
    version="0.2.0",
    description="Backend for the KATHA AI architecture & interior design platform.",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in all_routers:
    app.include_router(router, prefix="/api/v1")


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    details = [
        ErrorDetail(
            field=".".join(str(part) for part in error["loc"] if part != "body"),
            message=error["msg"],
        ).model_dump()
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(
            error="validation_error",
            message="Request validation failed",
            details=details,
        ).model_dump(),
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict) and {"error", "message"}.issubset(exc.detail.keys()):
        content = exc.detail
    else:
        content = ErrorResponse(
            error="http_error",
            message=str(exc.detail),
        ).model_dump()
    return JSONResponse(status_code=exc.status_code, content=content)


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {"status": "ok", "version": "0.2.0"}
