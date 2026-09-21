# ---- Stage 1: Build ----
FROM docker.io/library/node:24-alpine@sha256:d32cdf619f63fe0471182d08996dd516c6275bb5fd31ae06e55a570bd9e1ad43 AS builder

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
FROM docker.io/library/nginx:1.31-alpine@sha256:62ff2089abf5a9ed33bd232895bef5e22f7bb4b200675cec49a5ebc48e3d4ac8

ENV NGINX_ENVSUBST_FILTER=^(BACKEND_URL|BACKEND_HOST|S3_ENDPOINT_URL)$

COPY --from=builder /build/dist /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

EXPOSE 8080
