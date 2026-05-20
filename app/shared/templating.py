"""
shared/templating.py – Zentraler Template-Render-Helper
Sprint 3 Wave 2: CRM-050 Active-Route-Sync
Sprint 3 Wave 3: CRM-051 Presence + Avatar

Jeder Router nutzt render(request, template, **ctx) statt direkt
templates.TemplateResponse(). Damit ist Active-State strukturell garantiert.

Niko-Pattern: Longest-Prefix-Match fuer active_key.
Jan-Pattern: Breadcrumb-Mapping per active_key + optionaler extra_breadcrumb_label.
"""

import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from fastapi import Request
from fastapi.templating import Jinja2Templates

# Template-Verzeichnis: app/templates/
_TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "..", "templates")
templates = Jinja2Templates(directory=_TEMPLATE_DIR)

# APP_PREFIX aus .env (nie hardcoden)
APP_PREFIX = os.getenv("APP_PREFIX", "/mission-ctrl/crm-staging").rstrip("/")
COLDCALL_STAGING_PREFIX = os.getenv("COLDCALL_STAGING_PREFIX", "/coldcall-staging")

# Avatar-Verzeichnis
_AVATAR_DIR = Path(os.path.dirname(__file__)).parent / "static" / "avatars"

# Avatar-Farben pro User (Fallback wenn kein Bild)
_AVATAR_COLORS = ["#5870E2", "#7C3AED", "#0891B2", "#059669", "#D97706", "#E05870"]

# Allowlist mit Display-Daten (aus Migration 004 seed bekannt)
_ALLOWLIST_USERS = [
    {"email": "christian@cbh.ai",  "name": "Christian", "full_name": "Christian Zingg", "slug": "christian"},
    {"email": "andre@cbh.ai",      "name": "Andre",     "full_name": "Andre",            "slug": "andre"},
    {"email": "michi@cbh.ai",      "name": "Michi",     "full_name": "Michael",          "slug": "michi"},
    {"email": "marco@cbh.ai",      "name": "Marco",     "full_name": "Marco",            "slug": "marco"},
    {"email": "tim@cbh.ai",        "name": "Tim",       "full_name": "Tim",              "slug": "tim"},
]

# Display-Namen-Overrides (Spitznamen / Kurzform)
# Key = user_id / slug aus crm_user-Tabelle
_DISPLAY_NAME_OVERRIDES = {
    "christian": "Christian",   # Zingg weglassen
    "michael":   "Michi",        # Spitzname, Avatar-File heisst michi.png
}

# ─── NAV_ITEMS ────────────────────────────────────────────────────────────────
# Reihenfolge = Sidebar-Reihenfolge
# key: eindeutiger Bezeichner fuer Active-State
# path: absolute URL fuer Navigation
NAV_ITEMS = [
    {"key": "home",     "label": "Uebersicht",   "path": f"{APP_PREFIX}/",           "icon": "home"},
    {"key": "coldcall", "label": "Cold Calling",  "path": f"{COLDCALL_STAGING_PREFIX}/", "icon": "phone"},
    {"key": "crm",      "label": "CRM",           "path": f"{APP_PREFIX}/personen",   "icon": "users"},
    {"key": "pipeline", "label": "Pipeline",      "path": f"{APP_PREFIX}/pipeline",   "icon": "trending-up"},
    {"key": "projekte", "label": "Projekte",      "path": f"{APP_PREFIX}/projects",   "icon": "folder"},
]

# ─── Breadcrumb-Map ────────────────────────────────────────────────────────────
_BREADCRUMB_MAP = {
    "home":     [{"label": "Home", "path": f"{APP_PREFIX}/"}],
    "coldcall": [{"label": "Home", "path": f"{APP_PREFIX}/"},
                 {"label": "Cold Calling", "path": f"{COLDCALL_STAGING_PREFIX}/"}],
    "crm":      [{"label": "Home", "path": f"{APP_PREFIX}/"},
                 {"label": "CRM",  "path": f"{APP_PREFIX}/personen"}],
    "pipeline": [{"label": "Home", "path": f"{APP_PREFIX}/"},
                 {"label": "Deal Pipeline", "path": f"{APP_PREFIX}/pipeline"}],
    "projekte": [{"label": "Home", "path": f"{APP_PREFIX}/"},
                 {"label": "Projekte", "path": f"{APP_PREFIX}/projects"}],
    "settings": [{"label": "Home", "path": f"{APP_PREFIX}/"},
                 {"label": "Einstellungen", "path": f"{APP_PREFIX}/settings"}],
}


# ─── Avatar + Presence Helpers ────────────────────────────────────────────────

def get_avatar_url(email: str, prefix: str = "") -> str | None:
    """
    Gibt die URL des Avatars zurück wenn eine .png oder .jpg Datei existiert.
    Slug = erster Teil der E-Mail-Adresse (lowercase, nur a-z0-9).
    Fallback: None → Template rendert Initialen.
    """
    slug = re.sub(r"[^a-z0-9]", "", email.split("@")[0].lower())
    for ext in ("png", "jpg", "jpeg"):
        if (_AVATAR_DIR / f"{slug}.{ext}").exists():
            return f"{prefix}/static/avatars/{slug}.{ext}"
    return None


def get_presence_dict(db_conn) -> dict[str, str]:
    """
    Gibt {slug: 'online'|'away'|'offline'} zurück für alle User in crm_user.
    Schwellen: < 5 Min = online, 5–30 Min = away, > 30 Min = offline.
    db_conn: offene SQLite-Connection (wird nicht geschlossen).
    """
    try:
        rows = db_conn.execute(
            "SELECT user_id, last_seen_at FROM crm_user WHERE active=1"
        ).fetchall()
    except Exception:
        return {}

    now = datetime.now(timezone.utc)
    result: dict[str, str] = {}
    for row in rows:
        slug = row["user_id"]
        last_seen_raw = row["last_seen_at"]
        if not last_seen_raw:
            result[slug] = "offline"
            continue
        try:
            # ISO8601 mit Z oder +00:00
            last_seen_raw = last_seen_raw.replace("Z", "+00:00")
            last_seen = datetime.fromisoformat(last_seen_raw)
            if last_seen.tzinfo is None:
                last_seen = last_seen.replace(tzinfo=timezone.utc)
            delta = now - last_seen
            if delta <= timedelta(minutes=5):
                result[slug] = "online"
            elif delta <= timedelta(minutes=30):
                result[slug] = "away"
            else:
                result[slug] = "offline"
        except (ValueError, TypeError):
            result[slug] = "offline"
    return result


def get_all_users(db_conn, current_email: str, prefix: str = "") -> list[dict]:
    """
    Gibt alle aktiven User als Liste von Dicts zurück, aktueller User zuerst.
    Dict-Keys: id (slug), slug, display_name, initials, role, color, avatar_url, is_current.
    """
    try:
        rows = db_conn.execute(
            "SELECT email, name, user_id, role, color_hex, last_seen_at "
            "FROM crm_user WHERE active=1 "
            "ORDER BY CASE WHEN email=? THEN 0 ELSE 1 END, name ASC",
            (current_email,)
        ).fetchall()
    except Exception:
        rows = []

    seen_slugs: set[str] = set()
    users = []
    for row in rows:
        slug = row["user_id"]
        # Duplikate (christian + christian.zingg gleicher user_id) deduplizieren
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)

        raw_name = row["name"] or slug.capitalize()
        # Display-Name-Override (Spitzname / Kurzform) hat Vorrang
        if slug in _DISPLAY_NAME_OVERRIDES:
            name = _DISPLAY_NAME_OVERRIDES[slug]
        else:
            # Nur Vorname anzeigen
            name = raw_name.split()[0] if raw_name else slug.capitalize()
        parts = raw_name.split()
        if len(parts) >= 2:
            initials = parts[0][0].upper() + parts[-1][0].upper()
        elif parts:
            initials = parts[0][:2].upper()
        else:
            initials = "?"

        color = row["color_hex"] or _AVATAR_COLORS[len(users) % len(_AVATAR_COLORS)]
        avatar_url = get_avatar_url(row["email"], prefix)

        users.append({
            "id":           slug,
            "slug":         slug,
            "display_name": name,
            "initials":     initials,
            "role":         row["role"],
            "color":        color,
            "avatar_url":   avatar_url,
            "is_current":   row["email"] == current_email,
        })

    return users


def _resolve_active(path: str) -> str:
    """Longest-Prefix-Match: /crm-staging/personen/123 → 'crm'"""
    # K-BUG-001: Extra-Prefixes fuer Routes die nicht unter dem NAV_ITEMS-Pfad liegen
    EXTRA_PREFIXES = {
        "pipeline": ["/deals"],
        "crm":      ["/unternehmen", "/touchpoints"],
    }
    best = "home"
    best_len = 0
    for item in NAV_ITEMS:
        if path.startswith(item["path"]) and len(item["path"]) > best_len:
            best, best_len = item["key"], len(item["path"])
    # Extra-Prefix-Check: laengster Match gewinnt
    for nav_key, prefixes in EXTRA_PREFIXES.items():
        for prefix in prefixes:
            full_prefix = f"{APP_PREFIX}{prefix}"
            if path.startswith(full_prefix) and len(full_prefix) > best_len:
                best, best_len = nav_key, len(full_prefix)
    # Fallback fuer Settings-Route
    if path.endswith("/settings") or "/settings" in path:
        return "settings"
    return best


def _build_breadcrumb(path: str, active_key: str, extra_label: str = None) -> list:
    """
    Gibt Liste von {label, path, active} zurueck.
    Letzter Eintrag: active=True (kein Link im Template).
    Bei 4+ Ebenen: Mittlere durch '...' ersetzen.
    extra_label: Name einer Detail-Entitaet (z.B. 'Klaus Hartmann').
    """
    base = _BREADCRUMB_MAP.get(active_key, [{"label": "Home", "path": f"{APP_PREFIX}/"}])
    crumbs = [dict(c) for c in base]

    if extra_label:
        crumbs.append({"label": extra_label, "path": None})

    # Truncation bei > 3 Ebenen (Jan-Regel)
    if len(crumbs) > 3:
        crumbs = [crumbs[0], {"label": "...", "path": None}] + crumbs[-2:]

    # Active-Markierung
    for i, c in enumerate(crumbs):
        c["active"] = (i == len(crumbs) - 1)

    return crumbs


def _get_current_user(request: Request) -> dict:
    """User aus Session mit Initialen + Avatar-Farbe berechnen."""
    user = request.session.get("user") if hasattr(request, "session") else None
    if not user:
        return {"name": "Unbekannt", "email": "", "initials": "?", "color_idx": 0}

    name = user.get("name", user.get("email", "?"))
    parts = name.split()
    if len(parts) >= 2:
        initials = parts[0][0].upper() + parts[-1][0].upper()
    elif parts:
        initials = parts[0][:2].upper()
    else:
        initials = "?"

    # user_id fuer Avatar-Farb-Rotation (user.id % 6)
    email = user.get("email", "")
    color_idx = sum(ord(c) for c in email) % 6

    return {
        "name": name,
        "email": email,
        "initials": initials,
        "color_idx": color_idx,
        "id": color_idx,  # fuer Template: current_user.id | int % 6
        "display_name": name,
    }


def render(request: Request, template: str, **ctx):
    """
    Zentraler Render-Helper.
    Injiziert: nav_items, active_key, breadcrumb, current_user, prefix, now_hour,
               all_users, presence.
    Optionaler ctx-Key: extra_breadcrumb_label.
    """
    from app.db import get_connection

    path = request.url.path
    active_key = _resolve_active(path)
    extra_label = ctx.pop("extra_breadcrumb_label", None)
    breadcrumb = _build_breadcrumb(path, active_key, extra_label)
    current_user = _get_current_user(request)
    now_hour = datetime.now(timezone.utc).hour
    prefix = request.scope.get("root_path", APP_PREFIX)

    # CRM Sub-Nav Tab: personen oder unternehmen (Longest-Prefix)
    if f"{APP_PREFIX}/unternehmen" in path:
        crm_tab = "unternehmen"
    elif f"{APP_PREFIX}/personen" in path or f"{APP_PREFIX}/touchpoints" in path:
        crm_tab = "personen"
    else:
        crm_tab = "personen"

    # Presence + User-Liste für Sidebar Account-Block
    all_users: list[dict] = []
    presence: dict[str, str] = {}
    try:
        conn = get_connection()
        try:
            presence = get_presence_dict(conn)
            all_users = get_all_users(conn, current_user.get("email", ""), prefix)
        finally:
            conn.close()
    except Exception:
        pass

    return templates.TemplateResponse(request, template, {
        "request":      request,
        "prefix":       prefix,
        "nav_items":    NAV_ITEMS,
        "active_key":   active_key,
        "crm_tab":      crm_tab,
        "breadcrumb":   breadcrumb,
        "current_user": current_user,
        "now_hour":     now_hour,
        "all_users":    all_users,
        "presence":     presence,
        **ctx,
    })
