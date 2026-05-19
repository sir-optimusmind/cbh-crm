#!/bin/bash
# BUG-05 Fix: Wrapper für seed_staging.py der venv aktiviert
# Nutzung: bash scripts/seed_staging.sh
# Oder: ./scripts/seed_staging.sh
set -e
cd /home/cbh/crm
source .venv/bin/activate
python3 scripts/seed_staging.py "$@"
