"""
app/shared/kanban_auth.py – Magic-Link Auth + Modul-Scope-Guards
Migration 014 / MVG Bewerber-Kanban

Variante B+ (Niko-Spec):
  - Magic-Link validiert gegen magic_link-Tabelle
  - Bei Hit: dieselbe request.session["user"]-Logik wie Google-SSO-Callback
  - external_role + allowed_modules aus crm_user
  - require_kanban_access(): kombinierter Guard (login + Modul-Scope)
"""

import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.db import get_connection
from app.auth import APP_PREFIX, get_current_user
from app.shared.session_expiry import set_session_expiry

import logging
logger = logging.getLogger(__name__)

router = APIRouter()

# Token-Lifetime: 7 Tage bis erstem Klick, danach sliding 14 Tage (Session-Cookie)
MAGIC_LINK_EXPIRE_DAYS = int(os.getenv("MAGIC_LINK_EXPIRE_DAYS", "7"))


# ─── Helper: Token generieren ─────────────────────────────────────────────────

def generate_magic_link(
    email: str,
    created_by: str,
    tenant_slug: str = "mvg_lektorat",
    expires_in_days: int = MAGIC_LINK_EXPIRE_DAYS,
) -> str:
    """
    Erstellt neuen Magic-Link-Token in DB, gibt vollständige URL zurück.
    token_hash = SHA-256 des raw-Token → DB speichert nur den Hash.
    """
    raw_token = secrets.token_hex(32)  # 64 Hex-Zeichen
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=expires_in_days)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO magic_link (token_hash, tenant_slug, email, expires_at, created_by)
            VALUES (?, ?, ?, ?, ?)
            """,
            (token_hash, tenant_slug, email, expires_at, created_by),
        )
        conn.commit()
    finally:
        conn.close()

    base = os.getenv("APP_BASE_URL", "https://hook.srv960331.hstgr.cloud")
    return f"{base}{APP_PREFIX}/auth/magic/{raw_token}"


def revoke_magic_link(token_hash: str) -> bool:
    """Setzt expires_at auf jetzt → ungültig bei nächstem Aufruf."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE magic_link SET expires_at=? WHERE token_hash=?",
            (now, token_hash),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ─── Lookup: crm_user für Partner ─────────────────────────────────────────────

def _lookup_or_create_partner(
    email: str,
    allowed_modules: str = "kanban:lektorat-mvg",
    conn=None,
) -> dict:
    """
    Sucht crm_user-Row für external_partner. Erstellt sie falls nicht vorhanden.
    Gibt User-Dict zurück (Format identisch zu SSO-Callback).

    conn: optional. Wenn übergeben, wird diese Connection genutzt (kein eigener open/close).
    Bugfix K-BUG-001: magic_link_login übergibt die eigene conn um Doppel-Writer-Lock zu vermeiden.
    """
    _own_conn = conn is None
    if _own_conn:
        conn = get_connection()
    try:
        row = conn.execute(
            "SELECT email, name, user_id, role, color_hex, external_role, allowed_modules "
            "FROM crm_user WHERE email=? AND active=1",
            (email,),
        ).fetchone()

        if row:
            return {
                "email":          row["email"],
                "name":           row["name"],
                "user_id":        row["user_id"],
                "role":           row["role"],
                "external_role":  row["external_role"],
                "allowed_modules": row["allowed_modules"] or allowed_modules,
                "color":          row["color_hex"] or "#6B7280",
            }

        # Partner noch nicht in DB → Row anlegen
        name_part = email.split("@")[0].replace(".", " ").title()
        user_id = email.split("@")[0].lower().replace(".", "")
        conn.execute(
            """
            INSERT INTO crm_user
              (email, name, user_id, role, external_role, allowed_modules, active, color_hex)
            VALUES (?, ?, ?, 'readonly', 'external_partner', ?, 1, '#6B7280')
            """,
            (email, name_part, user_id, allowed_modules),
        )
        # Commit nur wenn wir die eigene Connection verwalten
        if _own_conn:
            conn.commit()
        return {
            "email":          email,
            "name":           name_part,
            "user_id":        user_id,
            "role":           "readonly",
            "external_role":  "external_partner",
            "allowed_modules": allowed_modules,
            "color":          "#6B7280",
        }
    finally:
        if _own_conn:
            conn.close()


# ─── Scope-Guards ─────────────────────────────────────────────────────────────

def is_external_partner(request: Request) -> bool:
    """True wenn eingeloggter User external_role='external_partner' hat."""
    user = get_current_user(request)
    return user is not None and user.get("external_role") == "external_partner"


def has_module_access(request: Request, module_slug: str = "kanban:lektorat-mvg") -> bool:
    """
    True wenn User Zugriff auf das Modul hat.
    Intern (role admin/user): immer True.
    external_partner: prüft allowed_modules.
    """
    user = get_current_user(request)
    if not user:
        return False
    ext_role = user.get("external_role")
    if ext_role != "external_partner":
        return True  # CBH-intern: alle Module erlaubt
    modules = (user.get("allowed_modules") or "").split(",")
    modules = [m.strip() for m in modules]
    return module_slug in modules


def require_kanban_access(request: Request, module_slug: str = "kanban:lektorat-mvg"):
    """
    Kombinierter Guard: eingeloggt + Modul-Scope.
    Returns user-dict wenn OK, None wenn nicht.
    """
    user = get_current_user(request)
    if not user:
        return None
    if not has_module_access(request, module_slug):
        return None
    return user


def require_internal(request: Request):
    """
    Nur CBH-intern (kein external_partner).
    Returns user-dict oder None.
    """
    user = get_current_user(request)
    if not user:
        return None
    if user.get("external_role") == "external_partner":
        return None
    return user


# ─── Magic-Link Route ─────────────────────────────────────────────────────────

_EXPIRED_HTML = """<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Link abgelaufen – CBH MISSION CTRL</title>
  <link href="https://fonts.googleapis.com/css2?family=Barlow:wght@400;600;700;900&display=swap" rel="stylesheet">
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ background: #111111; color: #F0F0F0; font-family: 'Barlow', sans-serif;
           display: flex; align-items: center; justify-content: center; min-height: 100vh; }}
    .box {{ background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 12px;
            padding: 48px 40px; max-width: 420px; width: 100%; text-align: center; }}
    .brand {{ font-size: 11px; font-weight: 900; letter-spacing: 0.2em; text-transform: uppercase;
              color: #F0F0F0; margin-bottom: 4px; }}
    .brand-sub {{ font-size: 18px; font-weight: 900; letter-spacing: 0.1em; text-transform: uppercase;
                  color: #FFFB76; margin-bottom: 32px; }}
    .icon {{ font-size: 36px; margin-bottom: 16px; }}
    h2 {{ font-size: 18px; font-weight: 700; margin-bottom: 12px; color: #F0F0F0; }}
    p {{ font-size: 14px; color: #aaa; line-height: 1.6; }}
    .hint {{ margin-top: 20px; font-size: 13px; color: #6B7280; }}
  </style>
</head>
<body>
  <div class="box">
    <div class="brand">CBH</div>
    <div class="brand-sub">MISSION CTRL</div>
    <div class="icon">&#128279;</div>
    <h2>Dieser Link ist abgelaufen.</h2>
    <p>Bitte fordere einen neuen Link bei <strong>Christian</strong> an.</p>
    <p class="hint">christian@cbh.ai</p>
  </div>
</body>
</html>"""


def _write_kanban_audit(
    conn,
    action: str,
    author: str,
    tenant_slug: str = "mvg_lektorat",
    applicant_id: int | None = None,
    old_status: str | None = None,
    new_status: str | None = None,
    extra_json: str | None = None,
    user_email: str | None = None,
) -> None:
    """
    Schreibt in applicant_audit (append-only, kein UPDATE/DELETE).
    K-BUG-005: user_email wird separat befüllt (immer E-Mail, nie Display-Name).
    """
    # user_email fallback: wenn nicht explizit angegeben, nehmen wir author
    # (für Webhook = 'webhook', für SSO-User = E-Mail da author dort schon die E-Mail ist)
    _user_email = user_email or author
    try:
        conn.execute(
            """
            INSERT INTO applicant_audit
              (tenant_slug, applicant_id, action, old_status, new_status, author, extra_json, user_email)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (tenant_slug, applicant_id, action, old_status, new_status, author, extra_json, _user_email),
        )
    except Exception as exc:
        logger.warning("kanban audit write failed: %s", exc)


@router.get("/auth/magic/{raw_token}")
async def magic_link_login(request: Request, raw_token: str):
    """
    GET /auth/magic/<hex-token>
    Validiert Token → setzt Session → redirect Kanban-Board.
    Abgelaufener/verbrauchter Token → HTTP 200 Fehlerseite.
    """
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else None)

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM magic_link WHERE token_hash=?",
            (token_hash,),
        ).fetchone()

        if not row:
            logger.warning("magic_link: unknown token from %s", ip)
            return HTMLResponse(_EXPIRED_HTML, status_code=200)

        # Abgelaufen?
        expires_str = row["expires_at"].replace("Z", "+00:00")
        expires_at = datetime.fromisoformat(expires_str)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if datetime.now(timezone.utc) > expires_at:
            logger.warning("magic_link: expired token for %s", row["email"])
            return HTMLResponse(_EXPIRED_HTML, status_code=200)

        # Bereits benutzt?
        if row["used_at"]:
            # 1×-use: Token ist verbraucht, aber Session läuft noch (14-Tage-Sliding)
            # → wenn Session noch aktiv: durchlassen
            existing_user = request.session.get("user")
            if existing_user and existing_user.get("email") == row["email"]:
                return RedirectResponse(
                    url=f"{APP_PREFIX}/kanban/lektorat-mvg/", status_code=302
                )
            logger.warning("magic_link: already-used token from %s", ip)
            return HTMLResponse(_EXPIRED_HTML, status_code=200)

        # Token gültig → used_at setzen (1×-use)
        conn.execute(
            "UPDATE magic_link SET used_at=? WHERE token_hash=?",
            (now_iso, token_hash),
        )

        email = row["email"]
        tenant_slug = row["tenant_slug"] or "mvg_lektorat"

        # Partner-User aus DB holen (oder anlegen)
        # conn weitergeben: verhindert Doppel-Writer-Lock (K-BUG-001 Root-Cause Fix)
        user = _lookup_or_create_partner(email, allowed_modules="kanban:lektorat-mvg", conn=conn)

        # Session setzen – identisches Format wie Google-SSO-Callback
        request.session["user"] = {
            "email":          user["email"],
            "name":           user["name"],
            "user_id":        user["user_id"],
            "role":           user["role"],
            "external_role":  "external_partner",
            "allowed_modules": user["allowed_modules"],
            "color":          user["color"],
        }
        set_session_expiry(request)

        # ISO-Audit: Login
        _write_kanban_audit(
            conn,
            action="magic_link_login",
            author=email,
            tenant_slug=tenant_slug,
        )
        conn.commit()

        logger.info("magic_link login OK: %s", email)
        return RedirectResponse(
            url=f"{APP_PREFIX}/kanban/lektorat-mvg/", status_code=302
        )

    finally:
        conn.close()
