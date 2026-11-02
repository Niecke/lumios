# ---- Stage 1: Build ----
FROM docker.io/library/node:26.13.0-alpine@sha256:c6ad9e9c1d80f6eb607c26b4b0a132ff7a2344fad1c78ea3baa2a7d4c8de6d94 AS builder

WORKDIR /build

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build


# ---- Stage 2: Runtime ----
FROM docker.io/nginx/nginx-unprivileged:1.31.8-alpine@sha256:16de44aff58d6a3906f4eb1499d930378b7f0fa96fdebc7d10962d2b2a4e794b

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
