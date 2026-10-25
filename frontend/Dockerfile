# ---- Stage 1: Build ----
FROM docker.io/library/node:24-alpine@sha256:06d7adf3e0ef61a13f1d28682726366f97a15aa1888c934d3ecec86c33918b53 AS builder

WORKDIR /build

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build


# ---- Stage 2: Runtime ----
FROM docker.io/nginx/nginx-unprivileged:1.31-alpine@sha256:a2545a4b4fdebc62bd6a624ba64bea3a1b8bb6e71deabe973ceec621349d5301

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
