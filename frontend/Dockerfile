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
FROM docker.io/library/nginx:1.31-alpine@sha256:db35bfc6b2951e7f8a72db5db120288c127ffaeeb4a6d4b95a26fead017d5913

ENV NGINX_ENVSUBST_FILTER=^(BACKEND_URL|BACKEND_HOST|S3_ENDPOINT_URL)$

COPY --from=builder /build/dist /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

EXPOSE 8080
