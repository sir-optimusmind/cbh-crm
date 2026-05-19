"""
main.py – CBH MISSION CTRL CRM Module
FastAPI App – Sprint 1 + Sprint 2 + Sprint 3 (SSO)

APP_PREFIX kommt aus .env (PFLICHT, nie hardcoden).
SSO via Google OAuth (CRM-031/032/033/034).
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.db import init_db
from app.auth import router as auth_router, SECRET_KEY, SESSION_MAX_AGE, APP_PREFIX as AUTH_APP_PREFIX
from app.routes.personen import router as personen_router
from app.routes.unternehmen import router as unternehmen_router
from app.routes.deals import router as deals_router
from app.routes.touchpoints import router as touchpoints_router
from app.routes.projects import router as projects_router
from app.routes.pipeline import router as pipeline_router

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
    Alle anderen: require_login, sonst Redirect zu /auth/login.
    Middleware-Reihenfolge: SessionMiddleware laeuft VOR diesem Guard.
    """

    PUBLIC_PATHS = ("/health", "/auth/login", "/auth/callback", "/auth/logout")

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        root = APP_PREFIX
        # Pfad relativ zum root_path
        relative = path[len(root):] if path.startswith(root) else path
        if not relative:
            relative = "/"

        # Oeffentliche Pfade durchlassen
        if any(relative == p or relative.startswith(p) for p in self.PUBLIC_PATHS):
            return await call_next(request)

        # Session pruefen
        user = request.session.get("user")
        if not user:
            # next-URL fuer Post-Login-Redirect merken
            request.session["next"] = path
            return RedirectResponse(url=f"{root}/auth/login", status_code=302)

        # User in request.state ablegen (Backward-Kompatibilitaet)
        request.state.crm_user = user
        return await call_next(request)


# ─── Middleware registrieren (Reihenfolge: LIFO – letztes add_middleware laeuft zuerst) ──
# SessionMiddleware ZULETZT hinzufuegen → laeuft ZUERST (verarbeitet Cookie vor AuthGuard)
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
app.include_router(auth_router)
app.include_router(personen_router)
app.include_router(unternehmen_router)
app.include_router(deals_router)
app.include_router(touchpoints_router)
app.include_router(projects_router)
app.include_router(pipeline_router)


# ─── Health-Check (oeffentlich) ───────────────────────────────────────────────
@app.get("/health")
async def health():
    return JSONResponse({"status": "ok", "env": CRM_ENV, "auth": "sso"})


# ─── Root Redirect → /personen ────────────────────────────────────────────────
@app.get("/")
async def root(request: Request):
    prefix = request.scope.get("root_path", "")
    return RedirectResponse(url=f"{prefix}/personen", status_code=302)
