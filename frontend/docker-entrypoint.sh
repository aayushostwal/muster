#!/bin/sh
set -eu

node -e 'const fs = require("fs"); const value = process.env.MUSTER_API_URL || process.env.NEXT_PUBLIC_API_URL || process.env.VITE_API_URL || "http://localhost:8080"; fs.writeFileSync("/app/public/runtime-config.js", `window.__MUSTER_API_URL__ = ${JSON.stringify(value)};\n`);'

exec "$@"
