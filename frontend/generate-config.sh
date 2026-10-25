#!/bin/sh
# Writes the runtime configuration the SPA reads from window.__CONFIG__, so one
# image serves every environment. Runs from /docker-entrypoint.d before nginx.
# Writes to /tmp because the root filesystem is read-only; nginx serves both
# files from there.
set -e
esc() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }
cat > /tmp/config.js <<CONF
window.__CONFIG__ = {
  GOOGLE_CLIENT_ID: "$(esc "${GOOGLE_CLIENT_ID:-}")",
  LANDING_URL: "$(esc "${LANDING_URL:-}")",
  APP_URL: "$(esc "${APP_URL:-}")"
};
CONF
cat > /tmp/version.json <<VERSION
{
  "commit": "$(esc "${GIT_SHA:-dev}")",
  "version": "$(esc "${APP_VERSION:-dev}")",
  "built_at": "$(esc "${BUILD_TIMESTAMP:-unknown}")"
}
VERSION
