# ---- Stage 1: Build ----
FROM docker.io/library/node:24-alpine@sha256:d32cdf619f63fe0471182d08996dd516c6275bb5fd31ae06e55a570bd9e1ad43 AS builder

ARG GIT_SHA

WORKDIR /build

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
ENV VITE_GIT_SHA=${GIT_SHA}
RUN npm run build


# ---- Stage 2: Runtime ----
FROM docker.io/library/nginx:1.31-alpine@sha256:a3554c0d0b48177b1413c26e01f695334428020d9df01243fbae3e11cfd17417

ENV NGINX_ENVSUBST_FILTER=^(BACKEND_URL|BACKEND_HOST|S3_ENDPOINT_URL)$

COPY --from=builder /build/dist /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY generate-config.sh /docker-entrypoint.d/40-generate-config.sh
RUN chmod +x /docker-entrypoint.d/40-generate-config.sh

EXPOSE 8080
