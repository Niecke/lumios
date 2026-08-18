# ---- Stage 1: Build ----
FROM docker.io/library/node:24-alpine AS builder

ARG VITE_GOOGLE_CLIENT_ID
ARG VITE_LANDING_URL
ARG GIT_SHA

WORKDIR /build

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
ENV VITE_GIT_SHA=${GIT_SHA}
RUN npm run build


# ---- Stage 2: Runtime ----
FROM docker.io/library/nginx:1.31-alpine@sha256:4a73073bd557c65b759505da037898b61f1be6cbcc3c2c3aeac22d2a470c1752

ENV NGINX_ENVSUBST_FILTER=^(BACKEND_URL|BACKEND_HOST|S3_ENDPOINT_URL)$

COPY --from=builder /build/dist /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

EXPOSE 8080
