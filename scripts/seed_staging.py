#!/usr/bin/env python3
"""
CRM-008: Seed-Script (erweitert für CRM-QW-02 + CRM-QW-03)
Legt 10 Personen + 3 Firmen + Verknüpfungen an.
Realistische CBH-Kontext-Daten. Idempotent.

Neu: stimmung (kalt/warm/heiss) + last_contact_at
Verteilung: 4 kalt, 4 warm, 2 heiss
last_contact_at: 3 NULL, 3 Heute, 2 Vor 14 Tagen, 2 Vor 60 Tagen

Nutzung (BUG-05 Fix):
  cd /home/cbh/crm && python3 scripts/seed_staging.py
  (venv wird automatisch nicht benötigt wenn dotenv installiert ist, alternativ: .venv/bin/python3 scripts/seed_staging.py)
"""

import sys
import os
from datetime import datetime, timezone, timedelta

# Pfad zum CRM-Root damit app-Imports funktionieren
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# .env laden
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from app.db import get_connection, now_iso

OWNERS = ["christian", "andre", "michi", "marco", "tim"]

# Hilfsfunktionen für Datum-Offsets
def _days_ago(n: int) -> str:
    """ISO8601-Timestamp vor n Tagen."""
    dt = datetime.now(timezone.utc) - timedelta(days=n)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

TODAY = _days_ago(0)
DAYS_14 = _days_ago(14)
DAYS_60 = _days_ago(60)

FIRMEN = [
    {
        "name": "Bayern Automotive Group GmbH",
        "branche": "Automotive",
        "groesse_ma": 1200,
        "website": "https://bayernautomotive.de",
        "notes": "Tier-1-Zulieferer. Hauptkontakt über André.",
        "created_by": "andre",
    },
    {
        "name": "Müller Maschinenbau AG",
        "branche": "Maschinenbau",
        "groesse_ma": 450,
        "website": "https://mueller-mb.de",
        "notes": "Mittelständler. Entscheidungsebene Owner + CxO.",
        "created_by": "christian",
    },
    {
        "name": "EnergieWerk Digital GmbH",
        "branche": "Energiewirtschaft",
        "groesse_ma": 85,
        "website": "https://energiewerk.digital",
        "notes": "Scale-up. Schnelle Entscheidungswege.",
        "created_by": "michi",
    },
]

PERSONEN = [
    # Bayern Automotive Group (4 Personen)
    {
        "vorname": "Klaus",
        "nachname": "Hartmann",
        "email": "k.hartmann@bayernautomotive.de",
        "telefon": "+49 89 4512-100",
        "position": "Geschäftsführer",
        "prospect_level": "Owner",
        "stimmung": "heiss",
        "last_contact_at": TODAY,
        "notes": "Entscheider. Tennis-Affinität. Bevorzugt Direktkontakt.",
        "created_by": "andre",
        "firma": "Bayern Automotive Group GmbH",
        "rolle": "Geschäftsführer",
        "primary": True,
    },
    {
        "vorname": "Sandra",
        "nachname": "Weiß",
        "email": "s.weiss@bayernautomotive.de",
        "telefon": "+49 89 4512-201",
        "position": "Head of Operations",
        "prospect_level": "Head",
        "stimmung": "warm",
        "last_contact_at": TODAY,
        "notes": "Operativer Lead. Koordiniert Workshops.",
        "created_by": "andre",
        "firma": "Bayern Automotive Group GmbH",
        "rolle": "Ansprechpartnerin",
        "primary": True,
    },
    {
        "vorname": "Tobias",
        "nachname": "Fuchs",
        "email": "t.fuchs@bayernautomotive.de",
        "telefon": "+49 89 4512-312",
        "position": "Einkaufsleiter",
        "prospect_level": "Manager",
        "stimmung": "kalt",
        "last_contact_at": DAYS_60,
        "notes": "Budget-Freigaben über ihn.",
        "created_by": "marco",
        "firma": "Bayern Automotive Group GmbH",
        "rolle": "Einkauf",
        "primary": True,
    },
    # Müller Maschinenbau (3 Personen)
    {
        "vorname": "Petra",
        "nachname": "Müller",
        "email": "p.mueller@mueller-mb.de",
        "telefon": "+49 8131 7700-0",
        "position": "Inhaberin & CEO",
        "prospect_level": "Owner",
        "stimmung": "heiss",
        "last_contact_at": TODAY,
        "notes": "Inhaberfamilie, 2. Generation. Langfristige Denkweise.",
        "created_by": "christian",
        "firma": "Müller Maschinenbau AG",
        "rolle": "Geschäftsführerin",
        "primary": True,
    },
    {
        "vorname": "Markus",
        "nachname": "Bauer",
        "email": "m.bauer@mueller-mb.de",
        "telefon": "+49 8131 7700-55",
        "position": "CTO",
        "prospect_level": "CxO",
        "stimmung": "warm",
        "last_contact_at": DAYS_14,
        "notes": "Technologie-Entscheider. Digitalisierungsaffinität.",
        "created_by": "christian",
        "firma": "Müller Maschinenbau AG",
        "rolle": "Technologie",
        "primary": True,
    },
    {
        "vorname": "Lena",
        "nachname": "Schneider",
        "email": "l.schneider@mueller-mb.de",
        "telefon": "+49 8131 7700-80",
        "position": "HR-Leiterin",
        "prospect_level": "Head",
        "stimmung": "warm",
        "last_contact_at": DAYS_14,
        "notes": "Führungskräfteentwicklung als Einstiegsthema.",
        "created_by": "tim",
        "firma": "Müller Maschinenbau AG",
        "rolle": "HR",
        "primary": True,
    },
    # EnergieWerk Digital (3 Personen)
    {
        "vorname": "Jonas",
        "nachname": "Weber",
        "email": "j.weber@energiewerk.digital",
        "telefon": "+49 30 2200-401",
        "position": "CEO & Co-Founder",
        "prospect_level": "Owner",
        "stimmung": "warm",
        "last_contact_at": DAYS_60,
        "notes": "Ex-McKinsey. Sehr analytisch. Schnelle Entscheider.",
        "created_by": "michi",
        "firma": "EnergieWerk Digital GmbH",
        "rolle": "CEO",
        "primary": True,
    },
    {
        "vorname": "Anna",
        "nachname": "Koch",
        "email": "a.koch@energiewerk.digital",
        "telefon": "+49 30 2200-402",
        "position": "CPO",
        "prospect_level": "CxO",
        "stimmung": "kalt",
        "last_contact_at": None,
        "notes": "Produkt-Verantwortliche. OKR-Fan.",
        "created_by": "michi",
        "firma": "EnergieWerk Digital GmbH",
        "rolle": "Product",
        "primary": True,
    },
    # 2 Personen ohne feste Firma (Freelancer / Netzwerk)
    {
        "vorname": "Stefan",
        "nachname": "Richter",
        "email": "stefan.richter@gmail.com",
        "telefon": "+49 171 5544332",
        "position": "Freelance Berater",
        "prospect_level": "Other",
        "stimmung": "kalt",
        "last_contact_at": None,
        "notes": "Netzwerkkontakt über LinkedIn. Vermittelt in Automotive.",
        "created_by": "marco",
        "firma": None,
        "rolle": None,
        "primary": False,
    },
    {
        "vorname": "Birgit",
        "nachname": "Lang",
        "email": "b.lang@consulting-lang.de",
        "telefon": "+49 89 999-1234",
        "position": "Geschäftsführerin",
        "prospect_level": "Owner",
        "stimmung": "kalt",
        "last_contact_at": None,
        "notes": "Eigene Boutique-Beratung. Kooperationsgespräch ausstehend.",
        "created_by": "tim",
        "firma": None,
        "rolle": None,
        "primary": False,
    },
]


def seed():
    conn = get_connection()
    try:
        # ─── Firmen anlegen (idempotent per name) ─────────────────────────────
        firma_ids = {}
        for f in FIRMEN:
            existing = conn.execute(
                "SELECT id FROM unternehmen WHERE name = ?", (f["name"],)
            ).fetchone()
            if existing:
                firma_ids[f["name"]] = existing["id"]
                print(f"  [SKIP] Firma bereits vorhanden: {f['name']}")
            else:
                ts = now_iso()
                cur = conn.execute(
                    """INSERT INTO unternehmen (name, branche, groesse_ma, website, notes, created_by, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (f["name"], f["branche"], f["groesse_ma"], f["website"], f["notes"], f["created_by"], ts, ts)
                )
                firma_ids[f["name"]] = cur.lastrowid
                print(f"  [OK]   Firma angelegt: {f['name']} (id={cur.lastrowid})")

        conn.commit()

        # ─── Personen anlegen (idempotent per email) ──────────────────────────
        for p in PERSONEN:
            # Idempotenz-Check: email oder (vorname+nachname) wenn keine email
            if p["email"]:
                existing = conn.execute(
                    "SELECT id FROM person WHERE email = ?", (p["email"],)
                ).fetchone()
            else:
                existing = conn.execute(
                    "SELECT id FROM person WHERE vorname=? AND nachname=?",
                    (p["vorname"], p["nachname"])
                ).fetchone()

            if existing:
                person_id = existing["id"]
                # Stimmung + last_contact_at updaten falls noch auf Default
                conn.execute(
                    "UPDATE person SET stimmung=?, last_contact_at=? WHERE id=?",
                    (p["stimmung"], p["last_contact_at"], person_id)
                )
                print(f"  [UPDATE] Person: {p['vorname']} {p['nachname']} (stimmung={p['stimmung']}, last_contact={p['last_contact_at'][:10] if p['last_contact_at'] else 'NULL'})")
            else:
                ts = now_iso()
                cur = conn.execute(
                    """INSERT INTO person (vorname, nachname, email, telefon, position, prospect_level,
                       stimmung, last_contact_at, notes, created_by, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (p["vorname"], p["nachname"], p["email"], p["telefon"],
                     p["position"], p["prospect_level"], p["stimmung"], p["last_contact_at"],
                     p["notes"], p["created_by"], ts, ts)
                )
                person_id = cur.lastrowid
                print(f"  [OK]   Person angelegt: {p['vorname']} {p['nachname']} (id={person_id})")

            # Verknüpfung anlegen
            if p["firma"] and p["firma"] in firma_ids:
                unt_id = firma_ids[p["firma"]]
                existing_link = conn.execute(
                    "SELECT 1 FROM person_unternehmen WHERE person_id=? AND unternehmen_id=?",
                    (person_id, unt_id)
                ).fetchone()
                if existing_link:
                    print(f"         [SKIP] Verknüpfung bereits vorhanden")
                else:
                    conn.execute(
                        """INSERT INTO person_unternehmen (person_id, unternehmen_id, rolle, primary_company, created_at)
                           VALUES (?, ?, ?, ?, ?)""",
                        (person_id, unt_id, p["rolle"], 1 if p["primary"] else 0, now_iso())
                    )
                    print(f"         → verknüpft mit {p['firma']} (primary={p['primary']})")

        conn.commit()
        print("\nSeed abgeschlossen.")

        # ─── Kontrolle ───────────────────────────────────────────────────────
        n_p = conn.execute("SELECT COUNT(*) FROM person WHERE deleted_at IS NULL").fetchone()[0]
        n_u = conn.execute("SELECT COUNT(*) FROM unternehmen WHERE deleted_at IS NULL").fetchone()[0]
        n_pu = conn.execute("SELECT COUNT(*) FROM person_unternehmen").fetchone()[0]
        stimmung_dist = conn.execute(
            "SELECT stimmung, COUNT(*) as n FROM person WHERE deleted_at IS NULL GROUP BY stimmung"
        ).fetchall()
        print(f"  Personen gesamt: {n_p}")
        print(f"  Unternehmen gesamt: {n_u}")
        print(f"  Verknüpfungen: {n_pu}")
        print(f"  Stimmung-Verteilung: {[(r['stimmung'], r['n']) for r in stimmung_dist]}")

    except Exception as e:
        conn.rollback()
        print(f"FEHLER: {e}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    print("CRM Seed-Script startet...")
    seed()
