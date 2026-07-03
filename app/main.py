"""FastAPI app — routers, startup, static test page."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

import asyncio

from app.db import init_db
from app.routers.documents import router as documents_router
from app.routers.settings import router as settings_router
from app.services.retry import retry_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    task = asyncio.create_task(retry_loop())
    yield
    task.cancel()


app = FastAPI(title="AI Government Letter Register", lifespan=lifespan)
app.include_router(documents_router)
app.include_router(settings_router)

# Serve static files (test page)
STATIC_DIR = Path(__file__).parent / "static"
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
async def test_page():
    """Browser test page at / — covers upload → review → save → search."""
    test_html = STATIC_DIR / "test.html"
    if test_html.exists():
        return HTMLResponse(content=test_html.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>test.html not found</h1>", status_code=404)