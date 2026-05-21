"""
shared/drive_auth.py – CRM-063 + CRM-064 + CRM-065: Google Drive OAuth Token Management
Sprint 4 | 2026-05-20

Zustaendig fuer:
  - OAuth-Consent-Flow (GET /auth/google/start, GET /auth/google/callback)
  - Token-Storage: /home/cbh/crm/data/google_tokens/{user_slug}.json (chmod 600)
  - picker-token Endpoint (GET /drive/picker-token)
  - validate-folder Endpoint (POST /deals/{id}/drive-link)

Sicherheitsregeln:
  - Refresh-Token NIEMALS in Response-Body
  - Token-Files: chmod 600, chown cbh:cbh
  - CSRF via State-Parameter (32-byte hex, Session-Store)

Niko-Architektur-Referenz: Spec Abschnitt A + C.1 + C.2 + C.3
"""

import os
import json
import secrets
import logging
from html import escape
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request as GoogleRequest
from google.auth.exceptions import TransportError

from app.db import get_connection, write_audit_log, now_iso

logger = logging.getLogger(__name__)

router = APIRouter()

# ─── Konfiguration ────────────────────────────────────────────────────────────

GOOGLE_OAUTH_CLIENT_ID     = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
GOOGLE_OAUTH_CLIENT_SECRET = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "")
GOOGLE_OAUTH_REDIRECT_URI  = os.getenv(
    "GOOGLE_OAUTH_REDIRECT_URI",
    "https://hook.srv960331.hstgr.cloud/mission-ctrl/crm-staging/auth/google/callback"
)

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.file"

# Token-Storage-Verzeichnis
_TOKEN_DIR = Path(os.getenv("CRM_TOKEN_DIR", "/home/cbh/crm/data/google_tokens"))

APP_PREFIX = os.getenv("APP_PREFIX", "/mission-ctrl/crm-staging").rstrip("/")


# ─── Hilfsfunktionen ─────────────────────────────────────────────────────────

def _ensure_token_dir() -> None:
    """Stellt sicher dass das Token-Verzeichnis existiert (chmod 700)."""
    _TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(_TOKEN_DIR, 0o700)


def _user_slug(user_id: str) -> str:
    """Deriviert sicheren Dateinamen aus user_id (z.B. 'christian')."""
    import re
    return re.sub(r"[^a-z0-9_-]", "", user_id.lower())


def _token_path(user_id: str) -> Path:
    return _TOKEN_DIR / f"{_user_slug(user_id)}.json"


def _load_token(user_id: str) -> Optional[dict]:
    """Laedt Token-File fuer User. Gibt None zurueck wenn nicht vorhanden."""
    path = _token_path(user_id)
    if not path.exists():
        return None
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.warning("[drive_auth] Token-Ladeefehler fuer %s: %s", user_id, e)
        return None


def _save_token(user_id: str, token_data: dict) -> None:
    """Speichert Token-File mit chmod 600."""
    _ensure_token_dir()
    path = _token_path(user_id)
    with open(path, "w") as f:
        json.dump(token_data, f)
    os.chmod(path, 0o600)
    logger.info("[drive_auth] Token gespeichert fuer %s", user_id)


def _delete_token(user_id: str) -> None:
    """Loescht Token-File (bei Offboarding oder Revoke)."""
    path = _token_path(user_id)
    if path.exists():
        path.unlink()
        logger.info("[drive_auth] Token geloescht fuer %s", user_id)


def get_valid_credentials(user_id: str) -> Optional[Credentials]:
    """
    Laedt Credentials fuer User und refresht bei Bedarf.
    Gibt None zurueck wenn kein Token vorhanden.
    Raises google.auth.exceptions.RefreshError bei invalid_grant.
    """
    data = _load_token(user_id)
    if not data:
        return None

    creds = Credentials(
        token=data.get("access_token"),
        refresh_token=data.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=GOOGLE_OAUTH_CLIENT_ID,
        client_secret=GOOGLE_OAUTH_CLIENT_SECRET,
        scopes=[DRIVE_SCOPE],
    )

    # Expiry setzen falls vorhanden
    if data.get("expires_at"):
        creds.expiry = datetime.fromtimestamp(data["expires_at"], tz=timezone.utc).replace(tzinfo=None)

    # Refresh wenn Token abgelaufen oder innerhalb 60s ablaufend
    if creds.expired or creds.expiry is None:
        try:
            creds.refresh(GoogleRequest())
            # Aktualisierte Token-Daten zurueckschreiben
            _save_token(user_id, {
                "access_token":  creds.token,
                "refresh_token": data.get("refresh_token"),  # Refresh-Token nicht ueberschreiben
                "expires_at":    creds.expiry.timestamp() if creds.expiry else None,
            })
        except Exception as e:
            logger.warning("[drive_auth] Token-Refresh fehlgeschlagen fuer %s: %s", user_id, e)
            raise

    return creds


def validate_folder(user_id: str, folder_id: str) -> tuple[bool, dict]:
    """
    Validiert Drive-Ordner via API.
    Returns (True, meta) bei Erfolg, (False, {"error": ...}) bei Fehler.
    Timeout: 3s (bei Timeout: best-effort, kein Fehler)
    """
    import requests as _requests

    try:
        creds = get_valid_credentials(user_id)
        if not creds:
            return False, {"error": "no_token"}

        resp = _requests.get(
            f"https://www.googleapis.com/drive/v3/files/{folder_id}",
            params={"fields": "id,name,mimeType,webViewLink,driveId,capabilities"},
            headers={"Authorization": f"Bearer {creds.token}"},
            timeout=3,
        )

        if resp.status_code == 200:
            data = resp.json()
            if data.get("mimeType") != "application/vnd.google-apps.folder":
                return False, {"error": "not_a_folder"}
            return True, data
        elif resp.status_code == 404:
            return False, {"error": "folder_not_found"}
        elif resp.status_code in (401, 403):
            return False, {"error": "folder_not_accessible"}
        else:
            return False, {"error": f"drive_error_{resp.status_code}"}

    except _requests.exceptions.Timeout:
        # Bei Timeout: best effort – warnen, nicht blockieren
        logger.warning("[drive_auth] Drive-API Timeout bei Folder-Validation %s", folder_id)
        return True, {"warning": "drive_not_validated"}
    except Exception as e:
        logger.warning("[drive_auth] Folder-Validation-Fehler: %s", e)
        return False, {"error": str(e)}


def revoke_user_token(user_id: str) -> None:
    """
    User-Offboarding: Token-File loeschen + Google-Revoke-Call.
    """
    import requests as _requests
    data = _load_token(user_id)
    if data and data.get("access_token"):
        try:
            _requests.post(
                "https://oauth2.googleapis.com/revoke",
                params={"token": data["access_token"]},
                timeout=5,
            )
        except Exception as e:
            logger.warning("[drive_auth] Revoke-Call fehlgeschlagen: %s", e)
    _delete_token(user_id)


# ─── CRM-063 / CRM-069: OAuth-Consent-Endpoints ──────────────────────────────

@router.get("/auth/google/start")
async def google_drive_start(request: Request, next: str = "/pipeline"):
    """
    CRM-063: Startet Drive-OAuth-Consent-Flow fuer aktuell eingeloggten User.
    Scope: drive.file (Minimal-Scope – kein full drive access)
    CSRF: State-Parameter (32-byte hex) in Session.
    """
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url=f"{APP_PREFIX}/auth/login")

    state = secrets.token_hex(32)
    request.session["drive_oauth_state"] = state
    request.session["drive_oauth_next"] = next

    # Google Authorization URL bauen
    from urllib.parse import urlencode
    params = {
        "client_id":     GOOGLE_OAUTH_CLIENT_ID,
        "redirect_uri":  GOOGLE_OAUTH_REDIRECT_URI,
        "response_type": "code",
        "scope":         DRIVE_SCOPE,
        "access_type":   "offline",
        "prompt":        "consent",   # Erzwingt Refresh-Token-Ausgabe
        "state":         state,
    }
    auth_url = "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)

    # Audit-Log
    conn = get_connection()
    try:
        ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else None)
        write_audit_log(conn, user=user.get("user_id", "unknown"),
                        entity_type="drive_oauth", entity_id=0,
                        action="CREATE",
                        changed_fields={"event": "oauth_start", "scope": DRIVE_SCOPE},
                        ip_address=ip)
        conn.commit()
    finally:
        conn.close()

    return RedirectResponse(url=auth_url)


@router.get("/auth/google/callback")
async def google_drive_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    """
    CRM-063: OAuth-Callback – tauscht Code gegen Token, speichert in Token-File.
    State-Parameter validiert gegen Session (CSRF-Schutz).
    """
    user = request.session.get("user")
    if not user:
        return RedirectResponse(url=f"{APP_PREFIX}/auth/login")

    ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else None)
    user_id = user.get("user_id", "unknown")

    # Error-Param von Google (z.B. access_denied)
    if error:
        logger.warning("[drive_auth] OAuth-Fehler fuer %s: %s", user_id, error)
        return HTMLResponse(_error_page(f"Google-Verbindung abgebrochen: {error}"))

    # CSRF-State validieren
    expected_state = request.session.pop("drive_oauth_state", None)
    if not expected_state or expected_state != state:
        logger.warning("[drive_auth] CSRF-State-Fehler fuer %s", user_id)
        return HTMLResponse(_error_page("Sicherheitsfehler: State-Parameter ungueltig."), status_code=400)

    next_url = request.session.pop("drive_oauth_next", "/pipeline")

    if not code:
        return HTMLResponse(_error_page("Kein Authorization-Code erhalten."), status_code=400)

    # Token-Exchange via requests
    import requests as _requests
    try:
        resp = _requests.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code":          code,
                "client_id":     GOOGLE_OAUTH_CLIENT_ID,
                "client_secret": GOOGLE_OAUTH_CLIENT_SECRET,
                "redirect_uri":  GOOGLE_OAUTH_REDIRECT_URI,
                "grant_type":    "authorization_code",
            },
            timeout=10,
        )
        token_data = resp.json()
    except Exception as e:
        logger.error("[drive_auth] Token-Exchange fehlgeschlagen: %s", e)
        return HTMLResponse(_error_page("Verbindungsfehler beim Token-Tausch."), status_code=500)

    if "error" in token_data:
        logger.error("[drive_auth] Token-Exchange Fehler: %s", token_data)
        return HTMLResponse(_error_page(f"Token-Fehler: {token_data.get('error_description', token_data.get('error'))}"))

    # Nur noetige Felder persistieren (NIEMALS raw dump mit refresh_token in Logs)
    expires_in = token_data.get("expires_in", 3599)
    expires_at = datetime.now(timezone.utc).timestamp() + expires_in

    to_store = {
        "access_token":  token_data["access_token"],
        "refresh_token": token_data.get("refresh_token", ""),
        "expires_at":    expires_at,
    }

    if not to_store["refresh_token"]:
        logger.warning("[drive_auth] Kein Refresh-Token erhalten fuer %s – eventuell kein prompt=consent", user_id)

    _save_token(user_id, to_store)

    # Audit-Log (KEIN Token-Inhalt im Log)
    conn = get_connection()
    try:
        write_audit_log(conn, user=user_id,
                        entity_type="drive_oauth", entity_id=0,
                        action="CREATE",
                        changed_fields={"event": "oauth_callback_success", "user_id": user_id},
                        ip_address=ip)
        conn.commit()
    finally:
        conn.close()

    # Erfolgs-Page mit Redirect-Hinweis
    return HTMLResponse(_success_page(next_url))


# ─── CRM-064: picker-token Endpoint ──────────────────────────────────────────

@router.get("/drive/picker-token")
async def drive_picker_token(request: Request):
    """
    CRM-064: Gibt kurzlebigen Access-Token fuer Google Picker API zurueck.
    Refresh-Token verlässt NIEMALS den Server.
    """
    user = request.session.get("user")
    if not user:
        return JSONResponse(
            {"error": "not_authenticated",
             "redirect": f"{APP_PREFIX}/auth/login"},
            status_code=401
        )

    user_id = user.get("user_id", "")

    # Pruefen ob Token-File vorhanden
    data = _load_token(user_id)
    if not data:
        return JSONResponse(
            {"error": "not_authenticated",
             "requires_auth": True,
             "redirect": f"{APP_PREFIX}/auth/google/start?next=/pipeline"},
            status_code=401
        )

    # Credentials laden + ggf. refreshen
    try:
        from google.auth.exceptions import RefreshError
        creds = get_valid_credentials(user_id)
        if not creds:
            return JSONResponse(
                {"error": "not_authenticated",
                 "requires_auth": True,
                 "redirect": f"{APP_PREFIX}/auth/google/start?next=/pipeline"},
                status_code=401
            )
    except Exception as e:
        err_str = str(e)
        if "invalid_grant" in err_str or "Token has been expired" in err_str:
            # Refresh-Token ungueltig → Re-Consent
            _delete_token(user_id)
            return JSONResponse(
                {"error": "token_revoked",
                 "requires_auth": True,
                 "redirect": f"{APP_PREFIX}/auth/google/start?next=/pipeline"},
                status_code=401
            )
        logger.error("[drive_auth] picker-token Fehler: %s", e)
        return JSONResponse({"error": "token_error"}, status_code=500)

    # Audit-Log (kein Token im Log)
    ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else None)
    conn = get_connection()
    try:
        write_audit_log(conn, user=user_id,
                        entity_type="drive_token_request", entity_id=0,
                        action="CREATE",
                        changed_fields={"event": "picker_token_issued"},
                        ip_address=ip)
        conn.commit()
    finally:
        conn.close()

    # Expiry berechnen (Sekunden bis Token ablaeuft)
    expires_in = 3599
    if creds.expiry:
        delta = creds.expiry.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)
        expires_in = max(0, int(delta.total_seconds()))

    # NUR Access-Token zurueckgeben – niemals Refresh-Token
    return JSONResponse({
        "access_token": creds.token,
        "expires_in": expires_in,
    })


# ─── CRM-065: Drive-Link Endpoint (Validate + Persistierung) ─────────────────

@router.post("/deals/{deal_id}/drive-link")
async def deals_drive_link(request: Request, deal_id: int):
    """
    CRM-065: Validiert Drive-Ordner + persistiert Drive-Felder in project.
    Audit-Log: LINK_DRIVE
    """
    user = request.session.get("user")
    if not user:
        return JSONResponse({"error": "not_authenticated"}, status_code=401)

    user_id = user.get("user_id", "")
    ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else None)

    body = await request.json()
    folder_id   = (body.get("drive_folder_id", "") or "").strip()
    folder_name = (body.get("drive_folder_name", "") or "").strip()
    folder_url  = (body.get("drive_folder_url", "") or "").strip()

    if not folder_id:
        return JSONResponse({"error": "drive_folder_id ist Pflicht"}, status_code=422)

    # Drive-Validation mit Timeout-Handling
    ok, drive_meta = validate_folder(user_id, folder_id)
    warning = None

    if not ok:
        err = drive_meta.get("error", "unknown")
        if err == "not_a_folder":
            return JSONResponse({"error": "not_a_folder"}, status_code=422)
        elif err == "folder_not_accessible" or err == "folder_not_found":
            return JSONResponse({"error": "folder_not_accessible"}, status_code=422)
        elif err == "no_token":
            return JSONResponse(
                {"error": "not_authenticated",
                 "requires_auth": True},
                status_code=401
            )
        # Andere Fehler: best-effort persistieren (Drive-Down, Timeout wurde als ok=True zurueckgegeben)
    elif drive_meta.get("warning"):
        warning = drive_meta["warning"]

    # Projekt fuer diesen Deal laden
    conn = get_connection()
    try:
        proj = conn.execute(
            "SELECT id FROM project WHERE deal_id=? AND deleted_at IS NULL",
            (deal_id,)
        ).fetchone()

        if not proj:
            return JSONResponse({"error": "Kein Projekt fuer diesen Deal"}, status_code=404)

        project_id = proj["id"]
        ts = now_iso()

        conn.execute(
            "UPDATE project SET drive_folder_id=?, drive_folder_name=?, drive_folder_url=?, updated_at=? WHERE id=?",
            (folder_id, folder_name, folder_url, ts, project_id)
        )

        # Audit-Log: LINK_DRIVE
        write_audit_log(conn, user=user_id,
                        entity_type="project", entity_id=project_id,
                        action="LINK_DRIVE",
                        changed_fields={
                            "drive_folder_id":   folder_id,
                            "drive_folder_name": folder_name,
                            "drive_folder_url":  folder_url,
                        },
                        ip_address=ip)
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error("[drive_auth] drive-link Fehler: %s", e)
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        conn.close()

    resp = {"ok": True, "project_id": project_id}
    if warning:
        resp["warning"] = warning
    return JSONResponse(resp)


# ─── Helper: HTML-Pages ───────────────────────────────────────────────────────

def _success_page(next_url: str) -> str:
    """HTML-Seite nach erfolgreichem Drive-Connect."""
    return f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <meta http-equiv="refresh" content="2;url={APP_PREFIX}{next_url}">
  <title>Drive verbunden</title>
  <style>
    body {{ background:#111; color:#F0F0F0; font-family:'Barlow',sans-serif;
           display:flex; align-items:center; justify-content:center; min-height:100vh; margin:0; }}
    .box {{ background:#1a1a1a; border:1px solid #2a2a2a; border-radius:12px;
            padding:40px; max-width:400px; text-align:center; }}
    .icon {{ font-size:40px; margin-bottom:16px; }}
    h2 {{ color:#34D399; font-size:18px; margin-bottom:8px; }}
    p {{ color:#9CA3AF; font-size:13px; }}
  </style>
</head>
<body>
  <div class="box">
    <div class="icon">&#9989;</div>
    <h2>Google Drive verbunden!</h2>
    <p>Du wirst weitergeleitet... <a href="{APP_PREFIX}{next_url}" style="color:#FFFB76;">Klick hier</a> falls nicht.</p>
  </div>
</body>
</html>"""


def _error_page(msg: str) -> str:
    """HTML-Seite bei OAuth-Fehler."""
    return f"""<!DOCTYPE html>
<html lang="de">
<head>
  <meta charset="UTF-8">
  <title>Verbindungsfehler</title>
  <style>
    body {{ background:#111; color:#F0F0F0; font-family:'Barlow',sans-serif;
           display:flex; align-items:center; justify-content:center; min-height:100vh; margin:0; }}
    .box {{ background:#1a1a1a; border:1px solid #2a2a2a; border-radius:12px;
            padding:40px; max-width:400px; text-align:center; }}
    h2 {{ color:#EF4444; margin-bottom:8px; }}
    p {{ color:#9CA3AF; font-size:13px; margin-bottom:20px; }}
    a {{ color:#FFFB76; }}
  </style>
</head>
<body>
  <div class="box">
    <h2>Verbindungsfehler</h2>
    <p>{escape(msg)}</p>
    <a href="{APP_PREFIX}/pipeline">Zurueck zur Pipeline</a>
  </div>
</body>
</html>"""
