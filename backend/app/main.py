from contextlib import asynccontextmanager
import logging
import os

from agents import set_default_openai_key, set_tracing_disabled
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from openai import AsyncOpenAI

from app.api import analyze, conversations, market
from app.config import settings
from app.db.sqlite import init_db

logger = logging.getLogger(__name__)


def _configure_env() -> None:
    os.environ.setdefault("OPENAI_AGENTS_DISABLE_TRACING", "1")
    set_tracing_disabled(True)

    if settings.openai_api_key:
        os.environ["OPENAI_API_KEY"] = settings.openai_api_key
        set_default_openai_key(settings.openai_api_key.strip())
    else:
        logger.warning("OPENAI_API_KEY is not set")
    if settings.twelve_data_api_key:
        os.environ["TWELVE_DATA_API_KEY"] = settings.twelve_data_api_key
    if settings.fred_api_key:
        os.environ["FRED_API_KEY"] = settings.fred_api_key
    if settings.tavily_api_key:
        os.environ["TAVILY_API_KEY"] = settings.tavily_api_key


@asynccontextmanager
async def lifespan(app: FastAPI):
    _configure_env()
    await init_db()
    yield

app = FastAPI(title="Gold Research Agent", lifespan=lifespan)

origins = [o.strip() for o in settings.cors_origins.split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(conversations.router, prefix="/api")
app.include_router(analyze.router, prefix="/api")
app.include_router(market.router)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "openai_configured": bool(settings.openai_api_key),
        "twelve_data_configured": bool(settings.twelve_data_api_key),
        "fred_configured": bool(settings.fred_api_key),
        "tavily_configured": bool(settings.tavily_api_key),
    }


@app.get("/health/openai")
async def health_openai():
    if not settings.openai_api_key:
        return {"status": "error", "type": "MissingAPIKey", "message": "OPENAI_API_KEY is not set"}
    try:
        client = AsyncOpenAI(api_key=settings.openai_api_key.strip())
        await client.models.list()
        return {"status": "ok"}
    except Exception as exc:
        logger.exception("OpenAI connectivity check failed")
        return {"status": "error", "type": type(exc).__name__, "message": str(exc)}
