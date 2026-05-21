"""
app/routes/kanban.py – MVG Bewerber-Kanban Routes
Migration 014 | Sprint 5 | 2026-05-21

Routes:
  GET  /kanban/lektorat-mvg/                     Board-View
  GET  /kanban/lektorat-mvg/setup                Setup (nur internal)
  GET  /kanban/lektorat-mvg/api/applicants        JSON-Liste (Polling alle 30s)
  POST /kanban/lektorat-mvg/api/applicants        Neue Karte (Bearer-Token = Marcus-Webhook)
  PATCH /kanban/lektorat-mvg/api/applicants/{id}/status   Move-Card (HTMX)
  POST  /kanban/lektorat-mvg/api/applicants/{id}/comments Kommentar (HTMX)
  POST  /kanban/lektorat-mvg/setup/master-folder  Picker-Callback
  POST  /kanban/lektorat-mvg/setup/links          Magic-Link generieren
  POST  /kanban/lektorat-mvg/setup/links/{token_hash}/revoke  Token revoken
  GET   /kanban/lektorat-mvg/api/applicants/{id}/detail     Detail-Panel Partial
"""

import json
import logging
import os
import time
from datetime import datetime, timezone
from collections import defaultdict
from html import escape

from fastapi import APIRouter, Request, HTTPException, Header
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from app.db import get_connection
from app.shared.templating import render
from app.shared.kanban_auth import (
    require_kanban_access,
    require_internal,
    generate_magic_link,
    revoke_magic_link,
    _write_kanban_audit,
    is_external_partner,
)

logger = logging.getLogger(__name__)

GOOGLE_PICKER_API_KEY = os.getenv("GOOGLE_PICKER_API_KEY", "")
GOOGLE_PROJECT_NUMBER = os.getenv("GOOGLE_PROJECT_NUMBER", "")
KANBAN_WEBHOOK_TOKEN  = os.getenv("KANBAN_WEBHOOK_TOKEN", "")
TENANT_SLUG           = "mvg_lektorat"

# ── Rate-Limiter (einfach, in-memory, kein Redis) ──────────────────────────
_rate_counter: dict[str, list[float]] = defaultdict(list)
RATE_WINDOW = 60       # Sekunden
RATE_MAX    = 30       # Max Requests pro Fenster


def _check_rate_limit(token: str) -> bool:
    """Returns True wenn OK, False wenn Rate überschritten."""
    now = time.time()
    bucket = _rate_counter[token]
    # Alte Einträge raus
    _rate_counter[token] = [t for t in bucket if now - t < RATE_WINDOW]
    if len(_rate_counter[token]) >= RATE_MAX:
        return False
    _rate_counter[token].append(now)
    return True


router = APIRouter(prefix="/kanban/lektorat-mvg")


# ─── Helper ───────────────────────────────────────────────────────────────────

def _get_columns(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT col_key, label, position FROM kanban_columns WHERE tenant_slug=? ORDER BY position",
        (TENANT_SLUG,),
    ).fetchall()
    return [dict(r) for r in rows]


def _get_applicants_grouped(conn) -> dict[str, list[dict]]:
    """Returns {col_key: [applicant_dict, ...]} mit comment_count."""
    rows = conn.execute(
        """
        SELECT a.*,
               (SELECT COUNT(*) FROM applicant_comments c
                WHERE c.applicant_id=a.id AND c.tenant_slug=?) AS comment_count
        FROM applicants a
        WHERE a.tenant_slug=?
        ORDER BY a.status, a.position, a.created_at
        """,
        (TENANT_SLUG, TENANT_SLUG),
    ).fetchall()
    grouped: dict[str, list] = defaultdict(list)
    for row in rows:
        grouped[row["status"]].append(dict(row))
    return grouped


def _get_applicant(conn, applicant_id: int) -> dict | None:
    row = conn.execute(
        "SELECT * FROM applicants WHERE id=? AND tenant_slug=?",
        (applicant_id, TENANT_SLUG),
    ).fetchone()
    return dict(row) if row else None


def _get_comments(conn, applicant_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM applicant_comments WHERE applicant_id=? AND tenant_slug=? ORDER BY created_at",
        (applicant_id, TENANT_SLUG),
    ).fetchall()
    return [dict(r) for r in rows]


def _get_config(conn) -> dict:
    row = conn.execute(
        "SELECT * FROM kanban_config WHERE tenant_slug=?",
        (TENANT_SLUG,),
    ).fetchone()
    return dict(row) if row else {}


def _get_magic_links(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT token_hash, email, expires_at, used_at, created_at FROM magic_link "
        "WHERE tenant_slug=? ORDER BY created_at DESC",
        (TENANT_SLUG,),
    ).fetchall()
    return [dict(r) for r in rows]


# ─── Board-View ───────────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def kanban_board(request: Request):
    user = require_kanban_access(request)
    if not user:
        return RedirectResponse(url="/mission-ctrl/crm-staging/auth/login", status_code=302)

    conn = get_connection()
    try:
        columns = _get_columns(conn)
        grouped = _get_applicants_grouped(conn)
        config  = _get_config(conn)
        total   = sum(len(v) for v in grouped.values())
    finally:
        conn.close()

    return render(
        request, "kanban/lektorat_mvg.html",
        extra_breadcrumb_label="MVG Lektorat",
        columns=columns,
        grouped=grouped,
        config=config,
        total=total,
        is_external=is_external_partner(request),
        current_user_email=user.get("email", ""),
    )


# ─── Setup-Page (nur internal) ────────────────────────────────────────────────

@router.get("/setup", response_class=HTMLResponse)
async def kanban_setup(request: Request):
    user = require_internal(request)
    if not user:
        raise HTTPException(status_code=403, detail="Kein Zugang.")

    conn = get_connection()
    try:
        config      = _get_config(conn)
        magic_links = _get_magic_links(conn)
    finally:
        conn.close()

    return render(
        request, "kanban/lektorat_mvg_setup.html",
        extra_breadcrumb_label="MVG Setup",
        config=config,
        magic_links=magic_links,
        google_picker_api_key=GOOGLE_PICKER_API_KEY,
        google_project_number=GOOGLE_PROJECT_NUMBER,
    )


# ─── API: Applicant-Liste (JSON, HTMX-Polling) ───────────────────────────────

@router.get("/api/applicants")
async def api_applicants(request: Request):
    user = require_kanban_access(request)
    if not user:
        raise HTTPException(status_code=401, detail="Nicht eingeloggt.")

    conn = get_connection()
    try:
        grouped = _get_applicants_grouped(conn)
    finally:
        conn.close()

    # JSON-Response (HTMX pollt, erwartet JSON)
    return JSONResponse({col: apps for col, apps in grouped.items()})


# ─── API: Neue Karte (Webhook = Marcus, Bearer-Token) ────────────────────────

class NewApplicantBody(BaseModel):
    name: str             # "Nachname, Vorname" oder "Vorname Nachname"
    email: str | None = None
    source: str = "Direkt"
    remote: bool = False
    cv_drive_url: str | None = None
    notes: str | None = None


@router.post("/api/applicants")
async def api_create_applicant(
    request: Request,
    body: NewApplicantBody,
    authorization: str = Header(default=""),
):
    # Bearer-Token prüfen
    expected = f"Bearer {KANBAN_WEBHOOK_TOKEN}"
    if not KANBAN_WEBHOOK_TOKEN or authorization != expected:
        raise HTTPException(status_code=401, detail="Ungültiger Token.")

    # Rate-Limit
    token_key = authorization[-16:]  # letzte 16 Zeichen als Bucket-Key
    if not _check_rate_limit(token_key):
        raise HTTPException(status_code=429, detail="Rate limit überschritten.")

    # Name aufsplitten: "Nachname, Vorname" oder "Vorname Nachname"
    raw = body.name.strip()
    if "," in raw:
        parts = [p.strip() for p in raw.split(",", 1)]
        nachname, vorname = parts[0], parts[1] if len(parts) > 1 else ""
    else:
        parts = raw.split(" ", 1)
        vorname  = parts[0] if parts else raw
        nachname = parts[1] if len(parts) > 1 else ""

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    conn = get_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO applicants
              (tenant_slug, vorname, nachname, email, eingangsdatum, quelle,
               remote_tag, drive_subfolder_url, status, created_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'eingang', 'webhook')
            """,
            (
                TENANT_SLUG, vorname, nachname, body.email,
                now_iso, body.source,
                1 if body.remote else 0,
                body.cv_drive_url,
            ),
        )
        applicant_id = cur.lastrowid

        # Initialer Kommentar aus notes
        if body.notes:
            conn.execute(
                """
                INSERT INTO applicant_comments (tenant_slug, applicant_id, author, text)
                VALUES (?, ?, 'webhook', ?)
                """,
                (TENANT_SLUG, applicant_id, body.notes),
            )

        # Audit
        _write_kanban_audit(
            conn,
            action="created",
            author="webhook",
            tenant_slug=TENANT_SLUG,
            applicant_id=applicant_id,
            new_status="eingang",
        )
        conn.commit()
    finally:
        conn.close()

    logger.info("Kanban: new applicant %s via webhook", body.name)
    return JSONResponse({"ok": True, "id": applicant_id})


# ─── API: Move-Card (HTMX PATCH) ─────────────────────────────────────────────

class MoveBody(BaseModel):
    new_status: str


@router.patch("/api/applicants/{applicant_id}/status")
async def api_move_card(request: Request, applicant_id: int, body: MoveBody):
    user = require_kanban_access(request)
    if not user:
        raise HTTPException(status_code=401, detail="Nicht eingeloggt.")

    valid_statuses = {"eingang", "sichtung", "erstgespraech", "zweitgespraech", "absage"}
    if body.new_status not in valid_statuses:
        raise HTTPException(status_code=400, detail=f"Ungültiger Status: {body.new_status}")

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    author  = user.get("email", "unknown")

    conn = get_connection()
    try:
        row = _get_applicant(conn, applicant_id)
        if not row:
            raise HTTPException(status_code=404, detail="Bewerber nicht gefunden.")

        old_status = row["status"]
        if old_status == body.new_status:
            return JSONResponse({"ok": True, "changed": False})

        conn.execute(
            "UPDATE applicants SET status=?, last_modified_at=? WHERE id=? AND tenant_slug=?",
            (body.new_status, now_iso, applicant_id, TENANT_SLUG),
        )
        _write_kanban_audit(
            conn,
            action="moved",
            author=author,
            tenant_slug=TENANT_SLUG,
            applicant_id=applicant_id,
            old_status=old_status,
            new_status=body.new_status,
        )
        conn.commit()
    finally:
        conn.close()

    logger.info("Kanban: move %d %s→%s by %s", applicant_id, old_status, body.new_status, author)
    return JSONResponse({"ok": True, "changed": True, "old_status": old_status, "new_status": body.new_status})


# ─── API: Kommentar (HTMX POST) ──────────────────────────────────────────────

class CommentBody(BaseModel):
    text: str


@router.post("/api/applicants/{applicant_id}/comments")
async def api_add_comment(request: Request, applicant_id: int, body: CommentBody):
    user = require_kanban_access(request)
    if not user:
        raise HTTPException(status_code=401, detail="Nicht eingeloggt.")

    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Leerer Kommentar.")

    # K-BUG-005: author = Display-Name für UI, user_email = E-Mail für Audit
    author     = user.get("name") or user.get("email", "unknown")
    user_email = user.get("email", "unknown")
    now_iso    = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    conn = get_connection()
    try:
        if not _get_applicant(conn, applicant_id):
            raise HTTPException(status_code=404, detail="Bewerber nicht gefunden.")

        conn.execute(
            """
            INSERT INTO applicant_comments (tenant_slug, applicant_id, author, text, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (TENANT_SLUG, applicant_id, author, text, now_iso),
        )
        _write_kanban_audit(
            conn,
            action="commented",
            author=author,
            tenant_slug=TENANT_SLUG,
            applicant_id=applicant_id,
            user_email=user_email,
        )
        conn.commit()

        # HTMX-Response: Kommentar-Row Partial
        # K-BUG-002 Fix: User-Input über html.escape() escapen (XSS-Schutz)
        author_safe = escape(author)
        text_safe   = escape(text)
        ts_safe     = escape(now_iso[:16].replace('T', ' '))
        row_html = f"""<div class="comment-item" data-author="{author_safe}">
  <div class="comment-meta">
    <span class="comment-author">{author_safe}</span>
    <span class="comment-ts">{ts_safe}</span>
  </div>
  <div class="comment-text">{text_safe}</div>
</div>"""
    finally:
        conn.close()

    return HTMLResponse(row_html)


# ─── Detail-Panel Partial (HTMX GET) ─────────────────────────────────────────

@router.get("/api/applicants/{applicant_id}/detail", response_class=HTMLResponse)
async def api_detail_panel(request: Request, applicant_id: int):
    user = require_kanban_access(request)
    if not user:
        raise HTTPException(status_code=401, detail="Nicht eingeloggt.")

    conn = get_connection()
    try:
        applicant = _get_applicant(conn, applicant_id)
        if not applicant:
            raise HTTPException(status_code=404, detail="Bewerber nicht gefunden.")
        comments = _get_comments(conn, applicant_id)
        columns  = _get_columns(conn)
    finally:
        conn.close()

    return render(
        request, "kanban/lektorat_mvg_detail.html",
        applicant=applicant,
        comments=comments,
        columns=columns,
        current_user_name=user.get("name") or user.get("email", ""),
    )


# ─── Setup: Picker-Callback ───────────────────────────────────────────────────

class FolderBody(BaseModel):
    folder_id:   str
    folder_name: str
    folder_url:  str = ""


@router.post("/setup/master-folder")
async def setup_master_folder(request: Request, body: FolderBody):
    user = require_internal(request)
    if not user:
        raise HTTPException(status_code=403, detail="Kein Zugang.")

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO kanban_config (tenant_slug, master_folder_id, master_folder_name, master_folder_url, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(tenant_slug) DO UPDATE SET
              master_folder_id=excluded.master_folder_id,
              master_folder_name=excluded.master_folder_name,
              master_folder_url=excluded.master_folder_url,
              updated_at=excluded.updated_at
            """,
            (TENANT_SLUG, body.folder_id, body.folder_name, body.folder_url, now_iso),
        )
        conn.commit()
    finally:
        conn.close()

    return JSONResponse({"ok": True})


# ─── Setup: Magic-Link generieren ─────────────────────────────────────────────

class LinkBody(BaseModel):
    email: str
    expires_in_days: int = 7


@router.post("/setup/links")
async def setup_generate_link(request: Request, body: LinkBody):
    user = require_internal(request)
    if not user:
        raise HTTPException(status_code=403, detail="Kein Zugang.")

    creator = user.get("email", "unknown")
    url = generate_magic_link(
        email=body.email,
        created_by=creator,
        tenant_slug=TENANT_SLUG,
        expires_in_days=body.expires_in_days,
    )
    return JSONResponse({"ok": True, "url": url})


# ─── Setup: Token revoken ─────────────────────────────────────────────────────

@router.post("/setup/links/{token_hash}/revoke")
async def setup_revoke_link(request: Request, token_hash: str):
    user = require_internal(request)
    if not user:
        raise HTTPException(status_code=403, detail="Kein Zugang.")

    ok = revoke_magic_link(token_hash)
    return JSONResponse({"ok": ok})
