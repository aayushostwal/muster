#!/bin/sh
set -e

# Regenerate runtime-config.js from the VITE_API_URL env var docker-compose
# injects at container start, so client.ts can pick it up without a rebuild.
# Runs automatically: nginx:alpine executes every executable script under
# /docker-entrypoint.d/ before starting nginx.
API_URL="${VITE_API_URL:-http://localhost:8080}"
cat > /usr/share/nginx/html/runtime-config.js <<EOF
window.__MUSTER_API_URL__ = "${API_URL}";
EOF
