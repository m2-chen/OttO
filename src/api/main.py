"""
src/api/main.py
FastAPI application entry point.
"""

import logging
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)

from src.api.routes import router
from src.api.data_routes import data_router

app = FastAPI(title="EV Land — OttO API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)       # WebSocket voice endpoint
app.include_router(data_router)  # REST API for website

FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


# ---------------------------------------------------------------------------
# HTML page routes
# ---------------------------------------------------------------------------

@app.get("/")
async def home():
    return FileResponse(FRONTEND_DIR / "index.html")

@app.get("/catalogue")
async def catalogue():
    return FileResponse(FRONTEND_DIR / "catalogue.html")

@app.get("/vehicle")
async def vehicle():
    return FileResponse(FRONTEND_DIR / "vehicle.html")

@app.get("/services")
async def services():
    return FileResponse(FRONTEND_DIR / "services.html")

@app.get("/parts")
async def parts():
    return FileResponse(FRONTEND_DIR / "parts.html")

@app.get("/otto")
async def otto():
    return FileResponse(FRONTEND_DIR / "otto.html")

@app.get("/otto-test")
async def otto_test():
    return FileResponse(FRONTEND_DIR / "otto-test.html")

@app.get("/health")
async def health():
    return {"status": "ok", "service": "EV Land — OttO API"}
