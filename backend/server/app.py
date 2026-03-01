import logging
import os
import sys
import warnings
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Keep backward-compatible imports used across backend modules.
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from .dependencies import init_dependencies
from .medical_routes import router as medical_router
from .routers import (
    chat_router,
    frontend_router,
    report_router,
    research_router,
    websocket_router,
)

# Suppress Pydantic V2 migration warnings
warnings.filterwarnings("ignore", message="Valid config keys have changed in V2")
warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")

_LOGGING_CONFIGURED = False


def configure_logging_once() -> None:
    """Configure backend logging in an idempotent way."""
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return

    log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    root_logger = logging.getLogger()

    if not root_logger.handlers:
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )
    else:
        root_logger.setLevel(log_level)

    logging.getLogger("uvicorn.supervisors.ChangeReload").setLevel(logging.WARNING)

    research_logger = logging.getLogger("research")
    if research_logger.level == logging.NOTSET:
        research_logger.setLevel(log_level)

    _LOGGING_CONFIGURED = True


configure_logging_once()

logger = logging.getLogger(__name__)
logger.propagate = True

DOC_PATH = os.getenv("DOC_PATH", "./my-docs")
REPORT_STORE_PATH = Path(os.getenv("REPORT_STORE_PATH", os.path.join("data", "reports.json")))
FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


def _allowed_origins() -> list[str]:
    allowed_origins_env = os.getenv("CORS_ALLOW_ORIGINS")
    if allowed_origins_env:
        return [o.strip() for o in allowed_origins_env.split(",") if o.strip()]
    return [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://app.gptr.dev",
    ]


def mount_static_routes(app: FastAPI) -> None:
    """Mount static paths once during app initialization."""
    os.makedirs("outputs", exist_ok=True)
    app.mount("/outputs", StaticFiles(directory="outputs"), name="outputs")

    if FRONTEND_DIR.exists():
        app.mount("/site", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend")
        static_path = FRONTEND_DIR / "static"
        if static_path.exists():
            app.mount("/static", StaticFiles(directory=str(static_path)), name="static")
        logger.debug(f"Frontend mounted from: {FRONTEND_DIR}")
    else:
        logger.warning(f"Frontend directory not found: {FRONTEND_DIR}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("GPT Researcher API ready - local mode (no database persistence)")
    yield
    logger.info("Research API shutting down")


app = FastAPI(lifespan=lifespan)
mount_static_routes(app)

# Initialize app-wide dependencies (router/service/repository/storage)
init_dependencies(
    report_store_path=REPORT_STORE_PATH,
    doc_path=DOC_PATH,
    frontend_dir=FRONTEND_DIR,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Domain routers
app.include_router(medical_router)
app.include_router(frontend_router)
app.include_router(report_router)
app.include_router(research_router)
app.include_router(chat_router)
app.include_router(websocket_router)
