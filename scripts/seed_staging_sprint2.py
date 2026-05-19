#!/home/cbh/crm/.venv/bin/python3
"""
CRM-016: Sprint-2-Seed-Script
Legt Deals, Touchpoints und Projekte fuer QA-Cycle an.
Idempotent: prüft vor jedem Insert ob Datensatz bereits existiert.
Sprint-1-Daten bleiben erhalten.

Nutzung:
  cd /home/cbh/crm && .venv/bin/python3 scripts/seed_staging_sprint2.py
  oder: bash scripts/seed_staging_sprint2.sh
"""

import sys
import os
from datetime import datetime, timezone, timedelta, date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from app.db import get_connection, now_iso

TODAY = date.today().isoformat()
YESTERDAY = (date.today() - timedelta(days=1)).isoformat()
NEXT_WEEK = (date.today() + timedelta(days=7)).isoformat()
LAST_WEEK = (date.today() - timedelta(days=7)).isoformat()
TWO_WEEKS_AGO = (date.today() - timedelta(days=14)).isoformat()
LAST_MONTH = (date.today() - timedelta(days=30)).isoformat()


def get_person_id(conn, nachname: str):
    r = conn.execute(
        "SELECT id FROM person WHERE nachname=? AND deleted_at IS NULL LIMIT 1", (nachname,)
    ).fetchone()
    return r["id"] if r else None


def get_unternehmen_id(conn, name_fragment: str):
    r = conn.execute(
        "SELECT id FROM unternehmen WHERE name LIKE ? AND deleted_at IS NULL LIMIT 1",
        (f"%{name_fragment}%",)
    ).fetchone()
    return r["id"] if r else None


def upsert_deal(conn, *, titel, stage, owner, backup_owner=None, person_id=None,
                unternehmen_id=None, acv=None, lead_source=None, lead_type=None,
                icp_persona=None, notes=None, followup_datum=None, unterschrift_datum=None,
                projekt_start_datum=None, verlust_grund=None, retry_datum=None, products=None):
    """Legt Deal an wenn kein Deal mit gleichem Titel+Stage+Owner existiert."""
    existing = conn.execute(
        "SELECT id FROM deal WHERE titel=? AND owner=? AND deleted_at IS NULL",
        (titel, owner)
    ).fetchone()
    if existing:
        print(f"  [SKIP] Deal vorhanden: {titel}")
        return existing["id"]

    ts = now_iso()
    cur = conn.execute(
        """INSERT INTO deal (titel, stage, person_id, unternehmen_id, owner, backup_owner,
           acv, lead_source, lead_type, icp_persona, notes, followup_datum,
           unterschrift_datum, projekt_start_datum, verlust_grund, retry_datum,
           created_by, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (titel, stage, person_id, unternehmen_id, owner, backup_owner,
         acv, lead_source, lead_type, icp_persona, notes, followup_datum,
         unterschrift_datum, projekt_start_datum, verlust_grund, retry_datum,
         owner, ts, ts)
    )
    deal_id = cur.lastrowid
    print(f"  [CREATE] Deal: {titel} (stage={stage}, owner={owner}, id={deal_id})")

    if products:
        for p in products:
            conn.execute(
                "INSERT OR IGNORE INTO deal_product (deal_id, product) VALUES (?,?)",
                (deal_id, p)
            )
    return deal_id


def upsert_project(conn, *, deal_id, name, delivery_owner, contract_value=None,
                   outcome_definition=None, dok_link=None, start_date=None):
    existing = conn.execute(
        "SELECT id FROM project WHERE deal_id=? AND deleted_at IS NULL", (deal_id,)
    ).fetchone()
    if existing:
        print(f"  [SKIP] Projekt vorhanden für Deal {deal_id}")
        return existing["id"]

    ts = now_iso()
    cur = conn.execute(
        """INSERT INTO project (deal_id, name, delivery_owner, status, contract_value,
           start_date, outcome_definition, dok_link, ist_rechnungen, created_by, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (deal_id, name, delivery_owner, "active", contract_value, start_date,
         outcome_definition, dok_link, 0, delivery_owner, ts, ts)
    )
    proj_id = cur.lastrowid
    print(f"  [CREATE] Projekt: {name} (deal={deal_id}, id={proj_id})")
    return proj_id


def upsert_touchpoint(conn, *, deal_id=None, person_id=None, art, datum, erstellt_von, inhalt, naechster_schritt=None):
    # Einfache Dedup: gleicher Inhalt + Datum
    existing = conn.execute(
        "SELECT id FROM touchpoint WHERE inhalt=? AND datum=? AND deleted_at IS NULL",
        (inhalt, datum)
    ).fetchone()
    if existing:
        print(f"  [SKIP] Touchpoint vorhanden: {inhalt[:40]}...")
        return existing["id"]

    ts = now_iso()
    cur = conn.execute(
        """INSERT INTO touchpoint (deal_id, person_id, art, datum, erstellt_von, inhalt,
           naechster_schritt, created_at, created_by)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (deal_id, person_id, art, datum, erstellt_von, inhalt, naechster_schritt, ts, erstellt_von)
    )
    tp_id = cur.lastrowid
    print(f"  [CREATE] Touchpoint: {art} am {datum} ({inhalt[:40]})")
    return tp_id


def main():
    conn = get_connection()
    try:
        print("CRM Sprint-2-Seed startet...")

        # Person/Unternehmen IDs aus Sprint-1
        p_hartmann = get_person_id(conn, "Hartmann")
        p_weiss = get_person_id(conn, "Weiß")
        p_fuchs = get_person_id(conn, "Fuchs")
        p_bauer = get_person_id(conn, "Bauer")
        p_schneider = get_person_id(conn, "Schneider")

        u_automotive = get_unternehmen_id(conn, "Bayern Automotive")
        u_maschinenbau = get_unternehmen_id(conn, "Müller Maschinenbau")
        u_digital = get_unternehmen_id(conn, "EnergieWerk")

        # ─── 8 Deals für alle 6 Stages ────────────────────────────────────
        print("\n--- Deals ---")

        # 1. Opportunity: marco + christian (Backup-Owner-Test Solo-Gate ab S1)
        d_opp_marco = upsert_deal(conn,
            titel="RACE Workshop – Fuchs GmbH",
            stage="opportunity",
            owner="marco", backup_owner="christian",
            person_id=p_fuchs, unternehmen_id=u_maschinenbau,
            acv=8500.0, lead_source="linkedin", lead_type="unknown_unknown",
            icp_persona="speed_optimizer", followup_datum=NEXT_WEEK,
            products=["race"]
        )

        # 2. New: tim + backup
        d_new_tim = upsert_deal(conn,
            titel="Blindspot-Analyse – Digital GmbH",
            stage="new",
            owner="tim", backup_owner="christian",
            unternehmen_id=u_digital,
            acv=12000.0, lead_source="telefon", lead_type="lucky_deal",
            followup_datum=NEXT_WEEK,
            products=["blindspot"]
        )

        # 3. Discovery: christian + andre (Backup-Owner-Test Sales-Hygiene)
        d_disc_christian = upsert_deal(conn,
            titel="OKR-Training – Bayern Automotive",
            stage="discovery",
            owner="christian", backup_owner="andre",
            person_id=p_hartmann, unternehmen_id=u_automotive,
            acv=15000.0, lead_source="referral", lead_type="inbound",
            icp_persona="transformation_leader",
            products=["okr_training", "pm_training"]
        )

        # 4. Proposal Sent: tim + backup
        d_prop_tim = upsert_deal(conn,
            titel="Innovation Cell Setup – Müller Maschinenbau",
            stage="proposal_sent",
            owner="tim", backup_owner="michi",
            person_id=p_weiss, unternehmen_id=u_maschinenbau,
            acv=55000.0, lead_source="networking", lead_type="unknown_unknown",
            icp_persona="forward_thinking_owner",
            notes="Angebot wurde am " + TWO_WEEKS_AGO + " versendet. Nachfass-Termin steht.",
            products=["innovation_cell", "visionsworkshop"]
        )

        # 5. Won: christian + andre, mit allen Pflichtfeldern
        d_won = upsert_deal(conn,
            titel="Empower OS Implementierung – Automotive",
            stage="won",
            owner="christian", backup_owner="andre",
            person_id=p_bauer, unternehmen_id=u_automotive,
            acv=45000.0, lead_source="referral", lead_type="inbound",
            icp_persona="transformation_leader",
            unterschrift_datum=TWO_WEEKS_AGO,
            projekt_start_datum=TODAY,
            products=["empower_os"]
        )

        # 6. Won 2: marco + christian, kleinerer Deal
        d_won2 = upsert_deal(conn,
            titel="PM-Training – EnergieWerk Digital",
            stage="won",
            owner="marco", backup_owner="christian",
            person_id=p_schneider, unternehmen_id=u_digital,
            acv=7500.0, lead_source="linkedin", lead_type="unknown_unknown",
            unterschrift_datum=LAST_WEEK,
            projekt_start_datum=NEXT_WEEK,
            products=["pm_training"]
        )

        # 7. Lost: mit Verlustgrund
        d_lost = upsert_deal(conn,
            titel="RACE Workshop – Lokaler Mittelstand",
            stage="lost",
            owner="andre", backup_owner="christian",
            acv=9500.0, lead_source="cognism",
            verlust_grund="Budget nicht vorhanden. Kein strategisches Mandat vom GF. Retry Q4 2026.",
            retry_datum=(date.today() + timedelta(days=120)).isoformat(),
            products=["race"]
        )

        # 8. Opportunity 2: christian ohne backup → in new stage
        d_new_christian = upsert_deal(conn,
            titel="T&M Beratung – New Prospect",
            stage="new",
            owner="christian",
            acv=3000.0, lead_source="email", lead_type="inbound",
            products=["tm"]
        )

        conn.commit()

        # ─── Projekte für Won-Deals ────────────────────────────────────────
        print("\n--- Projekte ---")

        upsert_project(conn,
            deal_id=d_won,
            name="Empower OS – Automotive",
            delivery_owner="christian",
            contract_value=45000.0,
            outcome_definition="Team kann Empower OS selbstständig einsetzen. 3 Abteilungen aktiv.",
            dok_link="https://drive.google.com/drive/folders/example-folder-id",
            start_date=TODAY
        )

        upsert_project(conn,
            deal_id=d_won2,
            name="PM-Training – EnergieWerk",
            delivery_owner="marco",
            contract_value=7500.0,
            outcome_definition="PM-Team zertifiziert. Workshop + Follow-up abgeschlossen.",
            start_date=NEXT_WEEK
        )

        conn.commit()

        # ─── Touchpoints ──────────────────────────────────────────────────
        print("\n--- Touchpoints ---")

        # Auf deal_id
        upsert_touchpoint(conn, deal_id=d_disc_christian, person_id=p_hartmann,
            art="anruf", datum=LAST_WEEK, erstellt_von="christian",
            inhalt="Erstgespräch: Bedarf an OKR-Training für 3 Business Units. Entscheidungsträger: HR-Leiter + GF.",
            naechster_schritt="Angebot bis " + NEXT_WEEK + " senden")

        upsert_touchpoint(conn, deal_id=d_disc_christian, person_id=p_hartmann,
            art="meeting", datum=TWO_WEEKS_AGO, erstellt_von="christian",
            inhalt="Discovery-Workshop in München. Bedarf konkretisiert. ACV ca. 15k.",
            naechster_schritt="Proposal ausarbeiten")

        upsert_touchpoint(conn, deal_id=d_prop_tim, person_id=p_weiss,
            art="email", datum=LAST_MONTH, erstellt_von="tim",
            inhalt="Angebot für Innovation Cell Setup versendet. Kontaktperson: Sandra Weiß (Head of Innovation).",
            naechster_schritt="Follow-up-Anruf nach 1 Woche")

        upsert_touchpoint(conn, deal_id=d_prop_tim,
            art="anruf", datum=TWO_WEEKS_AGO, erstellt_von="tim",
            inhalt="Nachfassgespräch: Entscheidung steht noch aus. Weiteres Meeting in 2 Wochen.",
            naechster_schritt="Meeting " + NEXT_WEEK)

        upsert_touchpoint(conn, deal_id=d_won,
            art="meeting", datum=LAST_MONTH, erstellt_von="christian",
            inhalt="Kick-off Meeting Empower OS. Projektstruktur besprochen. Start diese Woche.",
            naechster_schritt="Setup-Session buchen")

        upsert_touchpoint(conn, deal_id=d_opp_marco, person_id=p_fuchs,
            art="linkedin", datum=LAST_WEEK, erstellt_von="marco",
            inhalt="LinkedIn-Nachricht: Interesse an RACE gezeigt nach Post über agile Transformation.",
            naechster_schritt="Follow-up-Anruf " + NEXT_WEEK)

        upsert_touchpoint(conn, deal_id=d_lost,
            art="anruf", datum=LAST_MONTH, erstellt_von="andre",
            inhalt="Abschlussgespräch: Kein Budget für 2026. Evtl. Retry im Q4.",
            naechster_schritt=None)

        # Auf person_id ohne deal
        if p_hartmann:
            upsert_touchpoint(conn, person_id=p_hartmann,
                art="notiz", datum=TODAY, erstellt_von="christian",
                inhalt="Klaus Hartmann: Entscheidungsträger bei Bayern Automotive. Sehr aufgeschlossen für Weiterbildung.",
                naechster_schritt=None)

        if p_weiss:
            upsert_touchpoint(conn, person_id=p_weiss,
                art="anruf", datum=LAST_WEEK, erstellt_von="tim",
                inhalt="Erstkontakt über Cognism. Sandra Weiß ist Head of Innovation. RACE + Innovation Cell relevant.",
                naechster_schritt="Pitch-Deck vorbereiten")

        if p_bauer:
            upsert_touchpoint(conn, person_id=p_bauer,
                art="meeting", datum=TWO_WEEKS_AGO, erstellt_von="christian",
                inhalt="Meeting mit Markus Bauer und CTO. Empower OS für digitale Transformation der Automotive-Sparte.",
                naechster_schritt="Proposal senden")

        # Touchpoints für Deal + Person (beide IDs)
        upsert_touchpoint(conn, deal_id=d_new_tim,
            art="email", datum=YESTERDAY, erstellt_von="tim",
            inhalt="Terminbestätigung für Erstgespräch nächste Woche. Tim und Christian nehmen teil.",
            naechster_schritt="Prep: Blindspot-Diagnose vorbereiten")

        upsert_touchpoint(conn, deal_id=d_opp_marco,
            art="anruf", datum=TODAY, erstellt_von="marco",
            inhalt="Kurzes Follow-up-Gespräch. Termin noch nicht fix. Follow-up in 1 Woche.",
            naechster_schritt="Nochmals anrufen am " + NEXT_WEEK)

        upsert_touchpoint(conn, deal_id=d_won2,
            art="meeting", datum=YESTERDAY, erstellt_von="marco",
            inhalt="Kick-off-Meeting PM-Training. 5 Teilnehmer, Start " + NEXT_WEEK + ".",
            naechster_schritt="Materialien vorbereiten")

        upsert_touchpoint(conn, deal_id=d_disc_christian,
            art="notiz", datum=TODAY, erstellt_von="christian",
            inhalt="Interne Notiz: ACV könnte auf 18k steigen wenn wir PM-Training einschließen.",
            naechster_schritt=None)

        upsert_touchpoint(conn, deal_id=d_prop_tim,
            art="meeting", datum=LAST_WEEK, erstellt_von="michi",
            inhalt="Zweites Gespräch mit Entscheidungsebene. Budget intern noch nicht freigegeben. Entscheidung bis Ende Monat.",
            naechster_schritt="Nachtelefonieren wenn keine Antwort bis " + NEXT_WEEK)

        conn.commit()

        # ─── Zusammenfassung ──────────────────────────────────────────────
        print("\n--- Sprint-2-Seed abgeschlossen ---")
        print(f"  Deals gesamt: {conn.execute('SELECT COUNT(*) FROM deal WHERE deleted_at IS NULL').fetchone()[0]}")
        print(f"  Touchpoints gesamt: {conn.execute('SELECT COUNT(*) FROM touchpoint WHERE deleted_at IS NULL').fetchone()[0]}")
        print(f"  Projekte gesamt: {conn.execute('SELECT COUNT(*) FROM project WHERE deleted_at IS NULL').fetchone()[0]}")
        print(f"  Stage-Verteilung:")
        for row in conn.execute("SELECT stage, COUNT(*) FROM deal WHERE deleted_at IS NULL GROUP BY stage ORDER BY stage"):
            print(f"    {row[0]}: {row[1]}")

    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
