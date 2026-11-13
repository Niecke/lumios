# ---- Stage 1: Build ----
FROM docker.io/library/node:26.13.0-alpine@sha256:8996bb5821d62a8fd9bb27c1cb07462f3fdce6e47d640c6a881ead0b064ce216 AS builder

WORKDIR /build

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build


# ---- Stage 2: Runtime ----
FROM docker.io/nginx/nginx-unprivileged:1.31.8-alpine@sha256:0ec17b0dac55776357d46d882bed7f3d504b0e4a0bc7379c7dbb74bd12b9d4da

ARG GIT_SHA=dev
ARG BUILD_TIMESTAMP=unknown
ENV GIT_SHA=${GIT_SHA}
ENV BUILD_TIMESTAMP=${BUILD_TIMESTAMP}

USER root

ENV NGINX_ENVSUBST_FILTER=^(BACKEND_URL|BACKEND_HOST|S3_ENDPOINT_URL)$

COPY --from=builder /build/dist /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY generate-config.sh /docker-entrypoint.d/40-generate-config.sh
RUN chmod +x /docker-entrypoint.d/40-generate-config.sh

# Unprivileged image: nginx runs as UID 101 and the chart mounts a read-only
# root filesystem. config.js and version.json are written to /tmp at start.
USER 101

EXPOSE 8080
