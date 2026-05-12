"""bartolo/dashboard/__init__.py — FastAPI app factory per Bartolo Dashboard v2."""

from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

THIS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = THIS_DIR.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from universal_repo_agent_v5 import DEFAULT_WORKSPACE, LOG_DIRNAME  # type: ignore


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(DEFAULT_WORKSPACE / LOG_DIRNAME, exist_ok=True)
    from pathlib import Path as _Path
    _Path.home().joinpath(".bartolo", "chats").mkdir(parents=True, exist_ok=True)
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Bartolo Dashboard",
        description="Centre de control de Bartolo — xat, models, repos, API keys",
        version="2.0.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from bartolo.dashboard.chat import router as chat_router
    from bartolo.dashboard.chat_routes import router as chat_api_router
    from bartolo.dashboard.models_routes import router as models_router
    from bartolo.dashboard.secrets_routes import router as secrets_router
    from bartolo.dashboard.tools_routes import router as tools_router
    from bartolo.dashboard.repos_routes import router as repos_router
    from bartolo.dashboard.databases_routes import router as databases_router
    from bartolo.dashboard.shell_routes import router as shell_router

    app.include_router(chat_router)
    app.include_router(chat_api_router)
    app.include_router(models_router)
    app.include_router(secrets_router)
    app.include_router(tools_router)
    app.include_router(repos_router)
    app.include_router(databases_router)
    app.include_router(shell_router)

    from fastapi.responses import HTMLResponse
    from bartolo.dashboard.templates import render_index

    @app.get("/")
    async def index():
        return HTMLResponse(content=render_index())

    return app
