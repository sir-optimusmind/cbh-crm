"""
main.py – CBH MISSION CTRL CRM Module
FastAPI App – Sprint 1 + Sprint 2 + Sprint 3 (SSO + Modul-Trennung)

APP_PREFIX kommt aus .env (PFLICHT, nie hardcoden).
SSO via Google OAuth (CRM-031/032/033/034).
Modul-Trennung: CRM / Pipeline / Projects (CRM-035/036).
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.db import init_db
from app.auth import router as auth_router, SECRET_KEY, SESSION_MAX_AGE

# ─── Modul-Router ─────────────────────────────────────────────────────────────
# CRM-Modul: Personen + Unternehmen + Touchpoints
from app.modules.crm.routes import router as crm_router
# Pipeline-Modul: Deals + Pipeline-Kanban
from app.modules.pipeline.routes import router as pipeline_router
# Projects-Modul
from app.modules.projects.routes import router as projects_router

# ─── Konfiguration aus .env ───────────────────────────────────────────────────
APP_PREFIX = os.getenv("APP_PREFIX", "/mission-ctrl/crm-staging").rstrip("/")
CRM_ENV    = os.getenv("CRM_ENV", "staging")


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

# ─── Auth-Guard Middleware ────────────────────────────────────────────────────
class AuthGuardMiddleware(BaseHTTPMiddleware):
    """
    Prueft Session bei jedem Request.
    Oeffentliche Pfade: /health, /auth/*
    Alle anderen: Session-Check, sonst Redirect zu /auth/login.

    Middleware-Reihenfolge (LIFO):
    SessionMiddleware wird NACH AuthGuardMiddleware registriert →
    SessionMiddleware laeuft ZUERST (verarbeitet Cookie) →
    AuthGuardMiddleware hat request.session verfuegbar.
    """

    PUBLIC_PATHS = ("/health", "/auth/login", "/auth/callback", "/auth/logout")

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        root = APP_PREFIX
        relative = path[len(root):] if path.startswith(root) else path
        if not relative:
            relative = "/"

        # Oeffentliche Pfade
        if any(relative == p or relative.startswith(p) for p in self.PUBLIC_PATHS):
            return await call_next(request)

        # Session pruefen
        user = request.session.get("user")
        if not user:
            request.session["next"] = path
            return RedirectResponse(url=f"{root}/auth/login", status_code=302)

        request.state.crm_user = user
        return await call_next(request)


# ─── Middleware registrieren (LIFO) ───────────────────────────────────────────
app.add_middleware(AuthGuardMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    session_cookie="cbh_session",
    max_age=SESSION_MAX_AGE,
    same_site="lax",
    https_only=True,
    domain="hook.srv960331.hstgr.cloud",
)

# ─── Router einbinden ─────────────────────────────────────────────────────────
# Auth-Router (Login/Callback/Logout)
app.include_router(auth_router)
# CRM-Modul: Personen + Unternehmen + Touchpoints (keine eigene URL-Prefix-Ebene,
# da die Routen ihre Pfade direkt definieren: /personen, /unternehmen, /touchpoints)
app.include_router(crm_router)
# Pipeline-Modul: Deals + Pipeline-Kanban (/deals, /pipeline)
app.include_router(pipeline_router)
# Projects-Modul: (/projects)
app.include_router(projects_router)


# ─── Health-Check (oeffentlich) ───────────────────────────────────────────────
@app.get("/health")
async def health():
    return JSONResponse({
        "status": "ok",
        "env": CRM_ENV,
        "auth": "sso",
        "modules": ["crm", "pipeline", "projects"]
    })


# ─── Root Redirect → /personen ────────────────────────────────────────────────
@app.get("/")
async def root(request: Request):
    prefix = request.scope.get("root_path", "")
    return RedirectResponse(url=f"{prefix}/personen", status_code=302)
