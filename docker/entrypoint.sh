#!/usr/bin/env bash
set -euo pipefail

# On a fresh server /data is empty: bring the database back from R2. Does nothing when the
# database already exists, or when R2 has no copy yet (first ever start).
litestream restore -if-db-not-exists -if-replica-exists /data/fragrance.db

# Litestream runs the backoffice as its child and replicates for as long as it lives.
exec litestream replicate -exec "uvicorn app.web:app --host 0.0.0.0 --port 8000 --proxy-headers"
