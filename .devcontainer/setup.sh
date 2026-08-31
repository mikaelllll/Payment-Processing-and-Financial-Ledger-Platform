#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
bash .devcontainer/ensure-running.sh
