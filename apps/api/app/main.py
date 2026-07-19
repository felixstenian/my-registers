from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.middleware import RequestContextMiddleware
from app.api.routes import auth, chat, days, health, media, records, weekly
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.logging import configure_logging


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings = get_settings()
    configure_logging(level=settings.log_level, fmt=settings.log_format)
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="my-registers-api",
        version="0.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestContextMiddleware)

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(media.router)
    app.include_router(chat.router)
    app.include_router(records.router)
    app.include_router(days.router)
    app.include_router(weekly.router)

    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": str(exc)},
        )

    return app


app = create_app()
