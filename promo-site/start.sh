#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
SITE_DIR=dist
export SPA_FALLBACK=1
export PORT="${PORT:-3000}"
exec node static-server.mjs "$SITE_DIR"
