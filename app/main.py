"""
main.py – CBH MISSION CTRL CRM Module
FastAPI App – Sprint 1

APP_PREFIX kommt aus .env (PFLICHT, nie hardcoden).
Default '/crm-staging' ist sicher fuer Staging.
"""

import os
import sys
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager

from app.db import init_db

# ─── Konfiguration aus .env ───────────────────────────────────────────────────
# APP_PREFIX MUSS aus .env kommen. Kein Hardcoding. Kein Exception.
APP_PREFIX = os.getenv("APP_PREFIX", "/crm-staging").rstrip("/")
CRM_ENV    = os.getenv("CRM_ENV", "staging")


# ─── Startup / Shutdown ───────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """DB-Schema beim Start anlegen (idempotent)."""
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


# ─── Health-Check (CRM-002 Akzeptanzkriterium) ───────────────────────────────
@app.get("/health")
async def health():
    """GET /crm-staging/health → {"status": "ok", "env": "staging"}"""
    return JSONResponse({"status": "ok", "env": CRM_ENV})
