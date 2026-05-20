#!/usr/bin/env bash
# Docker entrypoint — starts the policy server.
# All settings can be overridden with environment variables.
set -euo pipefail
exec python /app/server.py \
    --host="${SERVER_HOST:-0.0.0.0}" \
    --port="${SERVER_PORT:-8080}" \
    --fps="${SERVER_FPS:-20}" \
    --chunk="${SERVER_CHUNK:-20}"
