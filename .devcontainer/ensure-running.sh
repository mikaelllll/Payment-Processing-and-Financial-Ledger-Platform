#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

# postStart and postAttach can occur close together. A host-level lock prevents
# duplicate Compose builds while still making either lifecycle hook sufficient.
lock_file="${TMPDIR:-/tmp}/ledgerflow-codespace-start.lock"
exec 9>"$lock_file"
flock 9

echo "Starting LedgerFlow services…"
docker compose up --build --detach --wait
echo "LedgerFlow is ready. Run: bash .devcontainer/show-url.sh"
