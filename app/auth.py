"""
auth.py – Google SSO via Authlib + Starlette SessionMiddleware
CRM-031 / CRM-032 / CRM-033 / CRM-034

Credentials: /home/cbh/crm/.google_oauth.json (chmod 600, nicht im Repo)
User-Allowlist: crm_user-Tabelle in crm.db (Migration 004)

Ablauf:
  GET  /auth/login      → Redirect zu Google OAuth
  GET  /auth/callback   → Token tauschen, User validieren, Session setzen
  POST /auth/logout     → Session leeren, Redirect zu /auth/login
"""

import io
import json
import os
import logging
import struct
from datetime import datetime, timezone
from pathlib import Path

from authlib.integrations.starlette_client import OAuth
from starlette.config import Config
from starlette.middleware.sessions import SessionMiddleware
from fastapi import APIRouter, Request, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse, Response, JSONResponse

from app.db import get_connection, write_audit_log

logger = logging.getLogger(__name__)

# ─── OAuth-Credentials laden ──────────────────────────────────────────────────
_OAUTH_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    ".google_oauth.json"
)
with open(_OAUTH_PATH) as f:
    _creds = json.load(f)["web"]

config = Config(environ={
    "GOOGLE_CLIENT_ID":     _creds["client_id"],
    "GOOGLE_CLIENT_SECRET": _creds["client_secret"],
})

oauth = OAuth(config)
oauth.register(
    name="google",
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

# ─── Secret Key ───────────────────────────────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError(
        "SECURITY ERROR: SECRET_KEY fehlt. Bitte in .env setzen."
    )

# Session-Cookie-Lifetime: 14 Tage (sliding via Starlette)
SESSION_MAX_AGE = int(os.getenv("SESSION_MAX_AGE", str(14 * 24 * 3600)))

# Callback-URL – aus .env oder Default
OAUTH_CALLBACK_URL = os.getenv(
    "OAUTH_CALLBACK_URL",
    "https://hook.srv960331.hstgr.cloud/mission-ctrl/crm-staging/auth/callback"
)

# APP_PREFIX – wo die App gemountet ist (kein trailing slash)
APP_PREFIX = os.getenv("APP_PREFIX", "/mission-ctrl/crm-staging").rstrip("/")


# ─── User-Lookup gegen crm_user-Tabelle ──────────────────────────────────────

def _lookup_user(email: str) -> dict | None:
    """
    Prüft ob email in crm_user-Tabelle und active=1.
    Gibt User-Dict zurück oder None.
    """
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT email, name, user_id, role, color_hex FROM crm_user WHERE email=? AND active=1",
            (email,)
        ).fetchone()
        if row:
            return dict(row)
        return None
    finally:
        conn.close()


def _update_last_login(email: str) -> None:
    """Setzt last_login-Timestamp für User."""
    conn = get_connection()
    try:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        conn.execute(
            "UPDATE crm_user SET last_login=? WHERE email=?",
            (now, email)
        )
        conn.commit()
    finally:
        conn.close()


def _write_login_audit(email: str, action: str, ip: str | None = None) -> None:
    """Schreibt Login/Logout/LoginDenied in session_log (ISO-Audit)."""
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO session_log (email, action, ip_address) VALUES (?, ?, ?)",
            (email, action, ip)
        )
        conn.commit()
    except Exception as exc:
        # session_log-Fehler soll Login nicht blockieren
        logger.warning("session_log write failed: %s", exc)
    finally:
        conn.close()


# ─── Session-Hilfsfunktionen ─────────────────────────────────────────────────

def get_current_user(request: Request) -> dict | None:
    """Gibt den eingeloggten User-Dict zurück oder None.
    Prüft zusätzlich Midnight-Expiry (CRM-103).
    """
    user = request.session.get("user")
    if not user:
        return None
    # Midnight-Expiry prüfen
    if is_session_expired(request):
        request.session.clear()
        return None
    return user


def require_login(request: Request) -> dict | None:
    """
    Gibt User-Dict zurück oder None wenn nicht eingeloggt.
    Routes, die Auth verlangen, prüfen den Rückgabewert.
    """
    return get_current_user(request)


def is_admin(request: Request) -> bool:
    """True wenn eingeloggter User role='admin' hat."""
    user = get_current_user(request)
    return user is not None and user.get("role") == "admin"


# ─── SSO-Router ───────────────────────────────────────────────────────────────

router = APIRouter()

# Login-Page – HTML mit Google-Button
_LOGIN_HTML = """<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>CBH MISSION CTRL – Login</title>
  <link href="https://fonts.googleapis.com/css2?family=Barlow:wght@400;600;700;900&display=swap" rel="stylesheet">
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ background: #111111; color: #F0F0F0; font-family: 'Barlow', sans-serif;
           display: flex; align-items: center; justify-content: center; min-height: 100vh; }}
    .login-box {{ background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 12px;
                 padding: 48px 40px; max-width: 380px; width: 100%; text-align: center; }}
    .brand {{ font-size: 11px; font-weight: 900; letter-spacing: 0.2em; text-transform: uppercase;
              color: #F0F0F0; margin-bottom: 4px; }}
    .brand-sub {{ font-size: 18px; font-weight: 900; letter-spacing: 0.1em; text-transform: uppercase;
                  color: #FFFB76; margin-bottom: 32px; }}
    .btn-google {{ display: flex; align-items: center; justify-content: center; gap: 10px;
                   background: #FFFB76; color: #111111; font-weight: 700; font-size: 14px;
                   padding: 12px 24px; border-radius: 8px; border: none; cursor: pointer;
                   text-decoration: none; width: 100%; transition: background 0.15s; }}
    .btn-google:hover {{ background: #f0ec60; }}
    .hint {{ margin-top: 16px; font-size: 12px; color: #666; }}
    {error_style}
  </style>
</head>
<body>
  <div class="login-box">
    <img src="{app_prefix}/static/brand/Symbol-white-transparent.svg" alt="CBH Rockfist" style="height:55px;margin-bottom:20px;display:block;margin-left:auto;margin-right:auto;">
    <div class="brand">CBH</div>
    <div class="brand-sub">MISSION CTRL</div>
    {error_block}
    <a href="{login_url}" class="btn-google">
      <svg width="18" height="18" viewBox="0 0 18 18" fill="none">
        <path d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844c-.209 1.125-.843 2.078-1.796 2.717v2.258h2.908c1.702-1.567 2.684-3.874 2.684-6.615z" fill="#4285F4"/>
        <path d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332C2.438 15.983 5.482 18 9 18z" fill="#34A853"/>
        <path d="M3.964 10.71c-.18-.54-.282-1.117-.282-1.71s.102-1.17.282-1.71V4.958H.957C.347 6.173 0 7.548 0 9s.348 2.827.957 4.042l3.007-2.332z" fill="#FBBC05"/>
        <path d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0 5.482 0 2.438 2.017.957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z" fill="#EA4335"/>
      </svg>
      Mit Google anmelden
    </a>
    <p class="hint">Nur @cbh.ai Accounts haben Zugang.</p>
  </div>
</body>
</html>"""

_DENIED_HTML = """<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>CBH MISSION CTRL – Kein Zugang</title>
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
    .denied-icon {{ font-size: 40px; margin-bottom: 16px; }}
    h2 {{ font-size: 18px; font-weight: 700; margin-bottom: 12px; color: #F0F0F0; }}
    p {{ font-size: 14px; color: #aaa; line-height: 1.5; margin-bottom: 24px; }}
    a {{ color: #FFFB76; text-decoration: none; font-weight: 600; font-size: 13px; }}
    a:hover {{ text-decoration: underline; }}
    .email-badge {{ background: #2a2a2a; border: 1px solid #333; border-radius: 6px;
                    padding: 6px 12px; font-size: 13px; color: #aaa; display: inline-block;
                    margin-bottom: 20px; }}
  </style>
</head>
<body>
  <div class="box">
    <div class="brand">CBH</div>
    <div class="brand-sub">MISSION CTRL</div>
    <div class="denied-icon">&#128274;</div>
    <h2>Kein Zugang</h2>
    <div class="email-badge">{email}</div>
    <p>Dein Account hat keinen Zugang zu MISSION CTRL.<br>Wende dich an <strong>christian@cbh.ai</strong>.</p>
    <a href="{login_url}">&#8592; Anderen Account verwenden</a>
  </div>
</body>
</html>"""


@router.get("/auth/login")
async def login(request: Request):
    """Zeigt Login-Seite oder startet direkt OAuth-Flow."""
    redirect_uri = OAUTH_CALLBACK_URL
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/auth/callback")
async def auth_callback(request: Request):
    """OAuth-Callback: Token tauschen, User validieren, Session setzen."""
    ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else None)
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception as exc:
        logger.warning("OAuth-Token-Fehler: %s", exc)
        login_url = f"{APP_PREFIX}/auth/login"
        html = _LOGIN_HTML.format(
            app_prefix=APP_PREFIX,
            login_url=login_url,
            error_style=".error{background:rgba(220,38,38,0.15);border:1px solid #DC2626;color:#FCA5A5;padding:10px 14px;border-radius:6px;margin-bottom:20px;font-size:13px;}",
            error_block='<div class="error">Anmeldung fehlgeschlagen. Bitte erneut versuchen.</div>'
        )
        return HTMLResponse(content=html)

    userinfo = token.get("userinfo") or {}
    email = (userinfo.get("email") or "").lower().strip()

    if not email:
        login_url = f"{APP_PREFIX}/auth/login"
        html = _LOGIN_HTML.format(
            app_prefix=APP_PREFIX,
            login_url=login_url,
            error_style=".error{background:rgba(220,38,38,0.15);border:1px solid #DC2626;color:#FCA5A5;padding:10px 14px;border-radius:6px;margin-bottom:20px;font-size:13px;}",
            error_block='<div class="error">E-Mail konnte nicht gelesen werden.</div>'
        )
        return HTMLResponse(content=html)

    # User gegen Allowlist prüfen
    user = _lookup_user(email)
    if not user:
        logger.warning("Login verweigert: %s", email)
        _write_login_audit(email, "LOGIN_DENIED", ip)
        denied_html = _DENIED_HTML.format(
            email=email,
            login_url=f"{APP_PREFIX}/auth/login"
        )
        return HTMLResponse(content=denied_html, status_code=403)

    # Session setzen
    name = userinfo.get("name") or user["name"]
    request.session["user"] = {
        "email":    user["email"],
        "name":     name,
        "user_id":  user["user_id"],
        "role":     user["role"],
        "color":    user.get("color_hex", "#5870E2"),
    }

    # Midnight-Expiry in Session schreiben (CRM-103)
    set_session_expiry(request)

    # last_login + Audit
    _update_last_login(email)
    _write_login_audit(email, "LOGIN", ip)
    logger.info("Login OK: %s (%s)", email, user["role"])

    # Redirect: next-Parameter oder Root
    next_url = request.session.pop("next", None)
    if next_url and next_url.startswith("/"):
        return RedirectResponse(url=next_url, status_code=302)
    return RedirectResponse(url=f"{APP_PREFIX}/personen", status_code=302)


@router.post("/auth/logout")
async def logout(request: Request):
    """Session löschen, Redirect zur Login-Seite."""
    user = get_current_user(request)
    ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else None)
    if user:
        _write_login_audit(user.get("email", "unknown"), "LOGOUT", ip)
    request.session.clear()
    return RedirectResponse(url=f"{APP_PREFIX}/auth/login", status_code=302)


@router.get("/auth/logout")
async def logout_get(request: Request):
    """GET-Fallback für Logout (Link-Klick). Gleiche Logik wie POST."""
    user = get_current_user(request)
    ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else None)
    if user:
        _write_login_audit(user.get("email", "unknown"), "LOGOUT", ip)
    request.session.clear()
    return RedirectResponse(url=f"{APP_PREFIX}/auth/login", status_code=302)


# ─── Heartbeat-Endpoint ───────────────────────────────────────────────────────

@router.post("/auth/heartbeat")
async def heartbeat(request: Request):
    """
    POST /auth/heartbeat – Aktualisiert last_seen_at für den eingeloggten User.
    Wird vom Frontend alle 30s gepollt.
    Returns 204 No Content.
    """
    user = get_current_user(request)
    if not user:
        return Response(status_code=401)

    email = user.get("email", "")
    if not email:
        return Response(status_code=400)

    conn = get_connection()
    try:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        conn.execute(
            "UPDATE crm_user SET last_seen_at=? WHERE email=?",
            (now, email)
        )
        conn.commit()
    except Exception as exc:
        logger.warning("heartbeat UPDATE failed: %s", exc)
    finally:
        conn.close()

    return Response(status_code=204)


# ─── Avatar-Upload-Endpoint ───────────────────────────────────────────────────

_AVATAR_DIR = Path(os.path.dirname(os.path.abspath(__file__))) / "static" / "avatars"
_AVATAR_MAX_BYTES = 2 * 1024 * 1024  # 2 MB

# Magic Bytes: PNG = \x89PNG, JPEG = \xFF\xD8\xFF
_MAGIC_JPEG = bytes([0xFF, 0xD8, 0xFF])
_MAGIC_PNG  = bytes([0x89, 0x50, 0x4E, 0x47])


def _check_image_magic(data: bytes) -> str | None:
    """
    Prüft Magic Bytes (nicht Content-Type).
    Gibt 'jpeg' oder 'png' zurück, oder None wenn ungültig.
    """
    if data[:4] == _MAGIC_PNG:
        return "png"
    if data[:3] == _MAGIC_JPEG:
        return "jpeg"
    return None


@router.post("/auth/avatar/upload")
async def avatar_upload(request: Request, avatar_file: UploadFile = File(...)):
    """
    POST /auth/avatar/upload – Avatar-Upload für eingeloggten User.
    - Magic-Bytes-Validation (kein Content-Type-Trust)
    - Max 2 MB
    - Resize auf 200x200px (Pillow)
    - Dateiname IMMER aus current_user.email abgeleitet (Path Traversal unmöglich)
    - Audit-Log Eintrag
    """
    user = get_current_user(request)
    if not user:
        return JSONResponse({"error": "Nicht eingeloggt"}, status_code=401)

    email = user.get("email", "")
    if not email:
        return JSONResponse({"error": "Kein User"}, status_code=400)

    ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else None)

    # Datei lesen (mit Größenlimit)
    raw = await avatar_file.read(_AVATAR_MAX_BYTES + 1)
    if len(raw) > _AVATAR_MAX_BYTES:
        return JSONResponse({"error": "Datei zu groß. Maximum: 2 MB."}, status_code=413)

    # Magic-Bytes prüfen
    img_type = _check_image_magic(raw)
    if img_type is None:
        return JSONResponse({"error": "Nur JPEG und PNG erlaubt."}, status_code=415)

    # Pillow: Resize auf 200x200
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(raw))
        img = img.convert("RGB")  # EXIF entfernen, Farbraum normalisieren
        img.thumbnail((200, 200), Image.LANCZOS)
        # Auf 200x200 croppen (zentriert)
        if img.size != (200, 200):
            new_img = Image.new("RGB", (200, 200), (30, 30, 30))
            offset_x = (200 - img.width) // 2
            offset_y = (200 - img.height) // 2
            new_img.paste(img, (offset_x, offset_y))
            img = new_img
    except Exception as exc:
        logger.warning("Pillow Fehler beim Avatar-Resize: %s", exc)
        return JSONResponse({"error": "Bild konnte nicht verarbeitet werden."}, status_code=422)

    # Slug aus E-Mail ableiten (sicher, kein Client-Input)
    import re
    slug = re.sub(r"[^a-z0-9]", "", email.split("@")[0].lower())
    if not slug:
        return JSONResponse({"error": "Ungültige E-Mail."}, status_code=400)

    # Speichern (immer als .png, einheitlich)
    dest = _AVATAR_DIR / f"{slug}.png"
    _AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    dest.write_bytes(buf.getvalue())

    # Audit-Log
    conn = get_connection()
    try:
        write_audit_log(
            conn,
            user=email,
            entity_type="crm_user",
            entity_id=0,
            action="AVATAR_UPLOAD",
            changed_fields={"slug": slug, "bytes": len(raw)},
            ip_address=ip,
        )
        conn.commit()
    except Exception as exc:
        logger.warning("Audit-Log für Avatar-Upload fehlgeschlagen: %s", exc)
    finally:
        conn.close()

    logger.info("Avatar-Upload OK: %s → %s", email, dest)
    return JSONResponse({"ok": True, "url": f"/static/avatars/{slug}.png"})
