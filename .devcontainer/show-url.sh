#!/usr/bin/env bash
set -euo pipefail

if [[ -n "${CODESPACE_NAME:-}" && -n "${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN:-}" ]]; then
  frontend_url="https://${CODESPACE_NAME}-3000.${GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN}"
else
  frontend_url="http://localhost:3000"
fi

printf '\nLedgerFlow is ready.\n\nOpen the frontend:\n%s\n\nAPI documentation:\n%s/api/docs\n\n' \
  "$frontend_url" "$frontend_url"

if [[ "${1:-}" == "--open" ]]; then
  if [[ -n "${BROWSER:-}" && -x "${BROWSER}" ]]; then
    "${BROWSER}" "$frontend_url" >/dev/null 2>&1 &
    disown || true
    printf 'Opening the frontend in your browser…\n\n'
  elif command -v code >/dev/null 2>&1 && code --open-url "$frontend_url" >/dev/null 2>&1; then
    printf 'Opening the frontend in your browser…\n\n'
  else
    printf 'Automatic opening was unavailable. Ctrl+click the frontend URL above.\n\n'
  fi
fi
