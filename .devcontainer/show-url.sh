#!/usr/bin/env bash
set -euo pipefail

if [[ -n "${CODESPACE_NAME:-}" && -n "${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-}" ]]; then
  printf '\nLedgerFlow frontend:\nhttps://%s-3000.%s\n\nAPI documentation:\nhttps://%s-3000.%s/api/docs\n\n' \
    "$CODESPACE_NAME" "$GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN" \
    "$CODESPACE_NAME" "$GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN"
else
  printf '\nLedgerFlow frontend: http://localhost:3000\nAPI documentation: http://localhost:3000/api/docs\n\n'
fi

