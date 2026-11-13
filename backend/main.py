"""FinovaLabs FastAPI backend application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.config import get_allowed_origins, get_backend_settings
from backend.routes.analytics import router as analytics_router
from backend.routes.audits import router as audits_router
from backend.routes.companies import router as companies_router
from backend.routes.health import router as health_router
from backend.routes.reviews import router as reviews_router
from backend.routes.settings import router as settings_router
from finova_labs.database import DatabaseError, init_db
from finova_labs.exceptions import ConfigurationError
from finova_labs.logging_config import configure_logging, get_logger
from finova_labs.workflow import WorkflowError

logger = get_logger("backend")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize SQLite database schema, settings, and logging on server startup."""
    settings = get_backend_settings()
    configure_logging(settings)
    init_db(settings.db_file)
    logger.info("FinovaLabs FastAPI engine initialized (db=%s)", settings.db_file)
    yield
    logger.info("FinovaLabs FastAPI engine shut down cleanly.")


app = FastAPI(
    title="FinovaLabs Financial Audit API",
    description="REST API for SEC EDGAR 10-K metric extraction, Decimal normalization, explainable confidence scoring, financial validation, and governed human review.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS configuration for React frontend communication
origins = get_allowed_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Global Safe Error Handlers (Prevents stack trace leakage)
@app.exception_handler(WorkflowError)
async def workflow_exception_handler(request: Request, exc: WorkflowError) -> JSONResponse:
    logger.warning("Workflow error on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"detail": str(exc), "error_type": "WorkflowError"},
    )


@app.exception_handler(DatabaseError)
async def database_exception_handler(request: Request, exc: DatabaseError) -> JSONResponse:
    logger.error("Database error on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "A database operation failed while processing your request.",
            "hint": getattr(exc, "hint", "Check server logs for details."),
            "error_type": "DatabaseError",
        },
    )


@app.exception_handler(ConfigurationError)
async def config_exception_handler(request: Request, exc: ConfigurationError) -> JSONResponse:
    logger.error("Configuration error on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": str(exc),
            "hint": getattr(exc, "hint", "Check .env configuration."),
            "error_type": "ConfigurationError",
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled server exception on %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "An internal server error occurred. The event has been logged.",
            "error_type": exc.__class__.__name__,
        },
    )


# Register Routers
app.include_router(health_router)
app.include_router(companies_router)
app.include_router(audits_router)
app.include_router(analytics_router)
app.include_router(reviews_router)
app.include_router(settings_router)


@app.get("/")
def root():
    return {
        "service": "FinovaLabs API",
        "version": "1.0.0",
        "documentation": "/docs",
        "health": "/api/health",
    }

