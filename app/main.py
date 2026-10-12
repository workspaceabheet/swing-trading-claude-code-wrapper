import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.db import get_connection
from app.routers import run as run_router

# Resolved against this file's location, not the process's cwd -- so
# templates/static are found regardless of where the app is launched from.
PACKAGE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")

# Run with:  uvicorn app.main:app --host 127.0.0.1 --port ${PORT:-8000}
# Never bind 0.0.0.0 -- this is a local, single-user tool; 127.0.0.1-only
# binding is the sole access control (no auth/token layer in this project).


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: init the schema, then reconcile any 'running' row left behind
    # by a prior process (crash, kill -9, or host reboot) -- this process
    # just started, so that row cannot actually still be running.
    conn = get_connection()
    conn.execute(
        "UPDATE runs SET status = 'error', finished_at = ? WHERE status = 'running'",
        (datetime.now(timezone.utc).isoformat(),),
    )
    conn.commit()
    conn.close()
    yield
    # No shutdown-time cleanup needed in Slice 0.


def create_app() -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    app.include_router(run_router.router, prefix="/api")
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return templates.TemplateResponse(request, "index.html", {})

    @app.get("/history", response_class=HTMLResponse)
    async def history(request: Request):
        return templates.TemplateResponse(request, "history.html", {})

    return app


app = create_app()


def run() -> None:
    """Console-script entry point (see [project.scripts] in pyproject.toml)."""
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "8000")),
    )
