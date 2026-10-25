FROM docker.io/nginx/nginx-unprivileged:1.31-alpine@sha256:a2545a4b4fdebc62bd6a624ba64bea3a1b8bb6e71deabe973ceec621349d5301

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
