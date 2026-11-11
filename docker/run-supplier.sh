#!/usr/bin/env bash
# Collects one supplier and sends what changed. Dokploy runs it on a schedule; a failure
# reaches Telegram, so a broken login or a site change doesn't go unnoticed.
# Usage: run-supplier <supplier>
set -uo pipefail

if fragrance collect "$1"; then
  fragrance notify
else
  fragrance warn "$1: collection failed. See the Dokploy schedule log."
  exit 1
fi
