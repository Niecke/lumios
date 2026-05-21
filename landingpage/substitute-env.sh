#!/bin/sh
set -e
envsubst '${APP_URL} ${BACKEND_URL}' \
  < /usr/share/nginx/html/index.html \
  > /tmp/index.html && mv /tmp/index.html /usr/share/nginx/html/index.html
envsubst '${APP_URL} ${BACKEND_URL}' \
  < /usr/share/nginx/html/registration.js \
  > /tmp/registration.js && mv /tmp/registration.js /usr/share/nginx/html/registration.js
