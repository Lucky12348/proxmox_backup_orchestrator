from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.api.routes.health import router as health_router
from app.auth import validate_auth_settings
from app.core.config import get_settings
from app.db.init import create_tables, seed_database
from app.services.planning_scheduler import start_planning_scheduler, stop_planning_scheduler


settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_auth_settings()
    create_tables()
    if settings.app_env != "production":
        seed_database()
    start_planning_scheduler(settings)
    yield
    stop_planning_scheduler()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
app.include_router(health_router)
