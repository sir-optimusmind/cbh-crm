# Google OAuth Token Storage

Dieses Verzeichnis enthaelt OAuth-Refresh-Tokens pro CBH-User fuer den Google Drive Picker.

## Format

Jeder Token wird als JSON-Datei gespeichert: {username}.json

Beispiel: christian.json, andre.json, michi.json, marco.json, tim.json

## Token-Datei-Format (google-auth-library Standard)

{
  'token': 'ya29...',
  'refresh_token': '1//...',
  'token_uri': 'https://oauth2.googleapis.com/token',
  'client_id': '127825722716-autbi417hhh4fhuc0kbnumvu84qhmdkd',
  'client_secret': '...',
  'scopes': ['https://www.googleapis.com/auth/drive.file'],
  'expiry': '2026-05-20T23:00:00.000000Z'
}

## Berechtigungen

- Verzeichnis: chmod 700 (nur cbh-User lesbar)
- Jede Token-Datei: chmod 600 (nur cbh-User lesbar)
- Nach Token-Anlage: chmod 600 {user}.json erzwingen

## Sicherheitsregeln

- Refresh-Token NIEMALS in Logs, Response-Body oder Browser ausgeben
- Bei User-Offboarding: Token-File loeschen + Drive-API tokens.revoke aufrufen
- Token-Scope: drive.file (minimal - nur explizit ausgewaehlte Ordner)
- OAuth-Client: 127825722716-autbi417hhh4fhuc0kbnumvu84qhmdkd (Optimus-Client)

## Env-Variablen (in /home/cbh/crm/.env)

GOOGLE_OAUTH_CLIENT_ID=127825722716-autbi417hhh4fhuc0kbnumvu84qhmdkd
GOOGLE_OAUTH_CLIENT_SECRET=<secret>
GOOGLE_OAUTH_REDIRECT_URI=https://crm.cbh.ai/auth/google/callback
GOOGLE_PICKER_API_KEY=<key - Christian fuellt aus - STOPP>
GOOGLE_PROJECT_NUMBER=<project-number - aus Google Cloud Console>

## Token-Refresh-Logik (Niko-Spec Abschnitt A)

- Refresh-Token persistieren (access_type=offline, prompt=consent)
- Bei jedem API-Call: Access-Token-Expiry pruefen, bei < 60s automatisch refreshen
  via google.oauth2.credentials.Credentials.refresh()
- Bei invalid_grant: Re-Consent-Flow via /auth/google/start ausloesen
- Daily Cron (Phase 2): Tokens aelter als 6 Monate -> Re-Consent erzwingen

Stand: 2026-05-20 | Sprint 4 CRM-063 Foundation
