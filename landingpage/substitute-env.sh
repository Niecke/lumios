#!/bin/sh
# The root filesystem is read-only: assemble the site in /tmp/html, which
# nginx serves, and substitute the environment there.
set -e
mkdir -p /tmp/html
cp -R /usr/share/nginx/html/. /tmp/html/
envsubst '${APP_URL} ${BACKEND_URL}' \
  < /usr/share/nginx/html/index.html \
  > /tmp/html/index.html
envsubst '${APP_URL} ${BACKEND_URL}' \
  < /usr/share/nginx/html/registration.js \
  > /tmp/html/registration.js
esc() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }
cat > /tmp/html/version.json <<VERSION
{
  "commit": "$(esc "${GIT_SHA:-dev}")",
  "version": "$(esc "${APP_VERSION:-dev}")",
  "built_at": "$(esc "${BUILD_TIMESTAMP:-unknown}")"
}
VERSION
