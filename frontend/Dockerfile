# ---- Stage 1: Build ----
FROM docker.io/library/node:24-alpine AS builder

ARG VITE_GOOGLE_CLIENT_ID
ARG GIT_SHA

WORKDIR /build

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
ENV VITE_GIT_SHA=${GIT_SHA}
RUN npm run build


# ---- Stage 2: Runtime ----
FROM docker.io/library/nginx:1.29-alpine

ENV NGINX_ENVSUBST_FILTER=^(BACKEND_URL|BACKEND_HOST|S3_ENDPOINT_URL)$

COPY --from=builder /build/dist /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

EXPOSE 8080
