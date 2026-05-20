"""
shared/session_expiry.py – Midnight-Session-Expiry-Helper
CRM-103 / Auth-Polish Sprint 4 – 2026-05-20

Strategie: Option A (Session-Inhalt-Timestamp)
- Starlette SessionMiddleware unterstützt kein per-Cookie max_age.
- Beim Login wird `session_expiry_ts` (Unix-Timestamp der nächsten Mitternacht) in
  die Session geschrieben.
- Jede App prüft bei jedem Request ob die Session abgelaufen ist.
- Abgelaufene Session → clear() + Redirect zu Login.

Geteilt von: CRM (auth.py), ColdCall-Staging (auth.py), CRM-Landing (main.py)
"""

from datetime import datetime, timezone, timedelta
from fastapi import Request

# Session-Key unter dem der Expiry-Timestamp gespeichert wird
_EXPIRY_KEY = "session_expiry_ts"


def seconds_until_midnight() -> int:
    """
    Berechnet Sekunden von jetzt bis Mitternacht (lokale Serverzeit = UTC+2 / Europe/Berlin).
    Minimum 60s (Schutz vor Edge-Case: Login exakt bei Mitternacht).
    """
    now = datetime.now(timezone.utc)
    # Mitternacht = nächster Tag 00:00:00 UTC
    # Server läuft auf UTC → Mitternacht UTC = 02:00 CEST / 01:00 CET
    # Christian-Entscheidung: 0:00 Server-Zeit (UTC) = ausreichend als Reset-Punkt
    tomorrow_midnight = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    delta = int((tomorrow_midnight - now).total_seconds())
    return max(delta, 60)


def set_session_expiry(request: Request) -> None:
    """
    Speichert den Midnight-Expiry-Timestamp in der Session.
    Muss nach request.session["user"] = {...} aufgerufen werden.
    """
    now = datetime.now(timezone.utc)
    tomorrow_midnight = (now + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    request.session[_EXPIRY_KEY] = tomorrow_midnight.timestamp()


def is_session_expired(request: Request) -> bool:
    """
    Gibt True zurück wenn:
    - kein Expiry-Timestamp in der Session (Legacy-Sessions ohne Midnight-Logik)
    - Timestamp liegt in der Vergangenheit

    Legacy-Sessions (kein _EXPIRY_KEY): werden als abgelaufen behandelt
    → erzwingt einmaligen Re-Login nach Deploy.
    """
    expiry_ts = request.session.get(_EXPIRY_KEY)
    if expiry_ts is None:
        # Alte Session ohne Expiry-Marker → als abgelaufen behandeln
        return True
    now = datetime.now(timezone.utc).timestamp()
    return now >= expiry_ts
