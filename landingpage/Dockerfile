FROM docker.io/nginx/nginx-unprivileged:1.31.8-alpine@sha256:16de44aff58d6a3906f4eb1499d930378b7f0fa96fdebc7d10962d2b2a4e794b

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
