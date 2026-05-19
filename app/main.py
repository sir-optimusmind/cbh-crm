"""
main.py – CBH MISSION CTRL CRM Module
FastAPI App – Sprint 1

APP_PREFIX kommt aus .env (PFLICHT, nie hardcoden).
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.db import init_db
from app.routes.personen import router as personen_router
from app.routes.unternehmen import router as unternehmen_router

# ─── Konfiguration aus .env ───────────────────────────────────────────────────
APP_PREFIX = os.getenv("APP_PREFIX", "/mission-ctrl/crm-staging").rstrip("/")
CRM_ENV    = os.getenv("CRM_ENV", "staging")

_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
_STATIC_DIR   = os.path.join(os.path.dirname(__file__), "static")

templates = Jinja2Templates(directory=_TEMPLATE_DIR)


# ─── Startup / Shutdown ───────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


# ─── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="CBH MISSION CTRL – CRM",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
    root_path=APP_PREFIX,
)

# Router einbinden
app.include_router(personen_router)
app.include_router(unternehmen_router)


# ─── Health-Check ─────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return JSONResponse({"status": "ok", "env": CRM_ENV})


# ─── Root Redirect → /personen ────────────────────────────────────────────────
@app.get("/")
async def root(request: Request):
    prefix = request.scope.get("root_path", "")
    return RedirectResponse(url=f"{prefix}/personen", status_code=302)
