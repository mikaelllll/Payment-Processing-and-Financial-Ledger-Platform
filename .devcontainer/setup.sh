#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
docker compose up --build --detach --wait
echo "LedgerFlow is ready. Run: bash .devcontainer/show-url.sh"

