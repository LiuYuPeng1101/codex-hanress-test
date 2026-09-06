from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.lifespan import lifespan

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(api_router, prefix=settings.api_prefix)


@app.exception_handler(SQLAlchemyError)
async def database_unavailable(request, exc):
    return JSONResponse(
        status_code=503,
        content={"detail": {"code": "DATABASE_UNAVAILABLE"}},
        headers={"Retry-After": "1"},
    )
