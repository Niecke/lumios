FROM docker.io/nginx/nginx-unprivileged:1.31.8-alpine@sha256:f90ef283a8a580912aa56315c3ed8f54cf50c2e89ed7e6fbf4c53368b55d712f

USER root

ARG GIT_SHA=dev
ARG BUILD_TIMESTAMP=unknown
ENV GIT_SHA=${GIT_SHA}
ENV BUILD_TIMESTAMP=${BUILD_TIMESTAMP}

ENV APP_URL=https://lumios-app.niecke-it.de
ENV BACKEND_URL=https://lumios-api.niecke-it.de

COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY src/ /usr/share/nginx/html/
COPY substitute-env.sh /docker-entrypoint.d/40-substitute-env.sh
RUN chmod +x /docker-entrypoint.d/40-substitute-env.sh

# Unprivileged image: nginx runs as UID 101 and the chart mounts a read-only
# root filesystem. The rendered site is assembled in /tmp/html at start.
USER 101

EXPOSE 8080
