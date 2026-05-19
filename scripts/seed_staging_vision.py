#!/home/cbh/crm/.venv/bin/python3
"""
CRM-021/022: Vision-Felder Seed-Script
Ergänzt bestehende Personen und Unternehmen mit Beispiel-Daten
für karriere_stationen, persoenlichkeit_notizen, stimmung_cbh,
sense_of_urgency, financials, news_json etc.

Idempotent: UPDATE setzt Felder nur wenn sie noch NULL sind.

Nutzung:
  cd /home/cbh/crm && .venv/bin/python3 scripts/seed_staging_vision.py
"""

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from app.db import get_connection, now_iso


def enrich_person(conn, nachname: str, **fields):
    r = conn.execute(
        "SELECT id FROM person WHERE nachname=? AND deleted_at IS NULL LIMIT 1", (nachname,)
    ).fetchone()
    if not r:
        print(f"  [SKIP] Person nicht gefunden: {nachname}")
        return
    pid = r["id"]
    # Nur NULL-Felder aktualisieren (nicht überschreiben)
    set_parts = []
    vals = []
    for k, v in fields.items():
        set_parts.append(f"{k}=COALESCE({k}, ?)")
        vals.append(v)
    if not set_parts:
        return
    vals.append(pid)
    conn.execute(
        f"UPDATE person SET {', '.join(set_parts)} WHERE id=?", vals
    )
    print(f"  [ENRICH] Person {nachname} (id={pid}) updated")


def enrich_unternehmen(conn, name_fragment: str, **fields):
    r = conn.execute(
        "SELECT id FROM unternehmen WHERE name LIKE ? AND deleted_at IS NULL LIMIT 1",
        (f"%{name_fragment}%",)
    ).fetchone()
    if not r:
        print(f"  [SKIP] Unternehmen nicht gefunden: {name_fragment}")
        return
    uid = r["id"]
    set_parts = []
    vals = []
    for k, v in fields.items():
        set_parts.append(f"{k}=COALESCE({k}, ?)")
        vals.append(v)
    if not set_parts:
        return
    vals.append(uid)
    conn.execute(
        f"UPDATE unternehmen SET {', '.join(set_parts)} WHERE id=?", vals
    )
    print(f"  [ENRICH] Unternehmen {name_fragment} (id={uid}) updated")


def main():
    conn = get_connection()
    try:
        print("Vision-Felder Seed startet...")

        # ─── Personen: CRM-021 Felder ─────────────────────────────────────
        print("\n--- Personen: Vision-Felder ---")

        enrich_person(conn, "Hartmann",
            karriere_stationen=(
                "2019–heute: Head of HR bei Bayern Automotive AG, München\n"
                "2014–2019: Senior HR Manager bei Continental AG\n"
                "2009–2014: HR Business Partner bei Daimler AG\n"
                "Ausbildung: Betriebswirtschaft (LMU München, 2009)"
            ),
            persoenlichkeit_notizen=(
                "Strukturiert, datengetrieben. Braucht Zahlen und Referenz-Cases, bevor er entscheidet. "
                "Mag kein Consulting-Sprech – lieber konkret. "
                "Reagiert gut auf Peer-Vergleiche ('andere Automotive-Firmen machen das so'). "
                "Entscheidet langsam aber loyale Kunde wenn gewonnen."
            ),
            stimmung_cbh="positiv",
            linkedin_trigger_datum="2026-04-15",
            linkedin_trigger_notiz="Post über 'Leadership in der VUCA-Welt' – perfekter Anknüpfungspunkt für RACE-Methodik",
            umsatz_gesamt_cbh=15000.00
        )

        enrich_person(conn, "Weiß",
            karriere_stationen=(
                "2022–heute: Head of Innovation bei Müller Maschinenbau GmbH\n"
                "2017–2022: Innovation Manager bei Bosch Power Tools\n"
                "2012–2017: Projektleiterin bei McKinsey (Industrial Practice)\n"
                "Ausbildung: Maschinenbau + MBA (TU München)"
            ),
            persoenlichkeit_notizen=(
                "Sehr analytisch, McKinsey-Prägung sichtbar. Denkt in Frameworks. "
                "Offen für Innovation wenn Business Case sauber ist. "
                "Misstraut 'weichem' Content – braucht ROI-Argumentation. "
                "Direkte Kommunikation bevorzugt, mag keine langen Intros."
            ),
            stimmung_cbh="neutral",
            linkedin_url="https://linkedin.com/in/sandra-weiss-innovation"
        )

        enrich_person(conn, "Fuchs",
            karriere_stationen=(
                "2020–heute: CEO Fuchs Präzisionsteile GmbH (Familienunternehmen)\n"
                "2016–2020: COO bei Elring Klinger AG\n"
                "2010–2016: Werksleiter Daimler (Rastatt)\n"
                "Ausbildung: Maschinenbau (KIT Karlsruhe)"
            ),
            persoenlichkeit_notizen=(
                "Pragmatisch. Entscheidet schnell wenn Vertrauen da ist. "
                "Familienunternehmer-Mentalität: kein Overhead, direkte Linie. "
                "Reagiert sehr gut auf konkrete Erfolgsgeschichten aus der Branche. "
                "Trigger: Mitarbeiter-Retention und Geschwindigkeit bei Entscheidungen."
            ),
            stimmung_cbh="sehr_positiv",
            umsatz_gesamt_cbh=0.00
        )

        # ─── Unternehmen: CRM-022 Felder ──────────────────────────────────
        print("\n--- Unternehmen: Vision-Felder ---")

        enrich_unternehmen(conn, "Bayern Automotive",
            sense_of_urgency=(
                "Transformationsdruck durch E-Mobility-Shift. GF hat intern Restrukturierung "
                "angestoßen, HR muss Führungskräfte-Pipeline in 12 Monaten aufbauen."
            ),
            sense_of_opportunity=(
                "Neuer CHRO seit Jan 2026 – bringt frischen Wind. Budget für L&D in Q2 freigegeben. "
                "Hartmann ist Champion intern."
            ),
            umsatz_mio=380.0,
            rentabilitaet_notiz="Mittelständisch, EBIT ~6% (2025). Automotive-Druck, aber solide Substanz.",
            wachstum_notiz="Stabiles Wachstum +3% 2025. E-Mobility-Bereich +22% YoY.",
            eigentuemerstruktur="AG, 60% Streubesitz, 40% Gründerfamilie (Zweite Generation). Kein PE.",
            produkt_empfehlung="race",
            produkt_empfehlung_sekundaer="okr_training",
            cbh_umsatz_gesamt=15000.00,
            news_json=json.dumps([
                {
                    "datum": "2026-03-10",
                    "titel": "Bayern Automotive kündigt E-Mobility-JV mit Bosch an",
                    "quelle_url": "https://example.com/news/ba-bosch-jv",
                    "notiz": "JV bedeutet neues Management-Layer – Chance für Leadership-Programm"
                },
                {
                    "datum": "2026-01-20",
                    "titel": "Neuer CHRO Dr. Maria Berger bei Bayern Automotive",
                    "quelle_url": "https://example.com/news/ba-chro",
                    "notiz": "Hartmann berichtet direkt an sie – guter Einstieg für Sponsor-Gespräch"
                }
            ], ensure_ascii=False)
        )

        enrich_unternehmen(conn, "Müller Maschinenbau",
            sense_of_urgency=(
                "Fachkräftemangel kritisch: 3 Senior-PMs haben 2025 das Unternehmen verlassen. "
                "GF will PM-Kompetenz bis Ende 2026 intern aufbauen."
            ),
            sense_of_opportunity=(
                "Innovation-Initiative läuft seit Q1 2026. Sandra Weiß (Head of Innovation) "
                "hat Budget von GF erhalten. Innovation Cell Setup high priority."
            ),
            umsatz_mio=125.0,
            rentabilitaet_notiz="Familienunternehmen, EBIT ~11%. Solide Marge trotz Auftragsrückgang.",
            wachstum_notiz="-4% 2025 durch Automotive-Abschwung. Diversifikation in Robotik geplant.",
            eigentuemerstruktur="GmbH, 100% Familie Müller (3. Generation). CEO ist Sohn des Gründers.",
            produkt_empfehlung="innovation_cell",
            produkt_empfehlung_sekundaer="pm_training",
            news_json=json.dumps([
                {
                    "datum": "2026-04-05",
                    "titel": "Müller Maschinenbau investiert €5M in Robotik-Sparte",
                    "quelle_url": "https://example.com/news/mm-robotik",
                    "notiz": "Robotik-Expansion = neues Kompetenzfeld = Trainings-Bedarf wächst"
                }
            ], ensure_ascii=False)
        )

        enrich_unternehmen(conn, "EnergieWerk",
            sense_of_urgency=(
                "Regulatorik-Druck durch EU-Taxonomie ab 2027. Sustainability-Team muss aufgebaut werden."
            ),
            sense_of_opportunity=(
                "Neuer CEO seit Q4 2025 aus Digital-Branche. Sehr offen für moderne Führungsmethoden. "
                "Erste Gespräche sehr positiv."
            ),
            umsatz_mio=220.0,
            rentabilitaet_notiz="Energiesektor, stabile Marge ~9%. Regulatorik erhöht Kosten leicht.",
            wachstum_notiz="+8% 2025 durch Renewables-Bereich. Traditionelles Energiegeschäft -2%.",
            eigentuemerstruktur="GmbH & Co. KG. 70% Stadtwerke-Konsortium, 30% strategischer Investor.",
            produkt_empfehlung="empower_os",
            produkt_empfehlung_sekundaer="visionsworkshop"
        )

        conn.commit()

        print("\n--- Vision-Seed abgeschlossen ---")
        # Quick Stats
        enriched_p = conn.execute(
            "SELECT COUNT(*) FROM person WHERE karriere_stationen IS NOT NULL AND deleted_at IS NULL"
        ).fetchone()[0]
        enriched_u = conn.execute(
            "SELECT COUNT(*) FROM unternehmen WHERE sense_of_urgency IS NOT NULL AND deleted_at IS NULL"
        ).fetchone()[0]
        print(f"  Personen mit karriere_stationen: {enriched_p}")
        print(f"  Unternehmen mit sense_of_urgency: {enriched_u}")

    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
