import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.config import settings
from app.exceptions import AppError
from app.monitoring import attach_health_routes, configure_prometheus


def _configure_logging() -> None:
    """Route our ``app.*`` loggers to stderr at INFO so we actually see
    pipeline diagnostics (extraction, ingestion, normalization, etc.)
    instead of Python's default WARNING-only root handler.
    """
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        )
    else:
        root.setLevel(logging.INFO)
    for name in ("app", "mineru", "uvicorn.error"):
        logging.getLogger(name).setLevel(logging.INFO)


def create_app() -> FastAPI:
    _configure_logging()

    app = FastAPI(
        title="Knowledge Platform API",
        version="0.1.0",
        debug=settings.APP_DEBUG,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "app://obsidian.md",
            "http://localhost",
            "http://localhost:8000",
            "http://127.0.0.1",
            "http://127.0.0.1:8000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    attach_health_routes(app)
    app.include_router(api_router, prefix="/api/v1")
    configure_prometheus(app)
    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=settings.APP_DEBUG,
    )
