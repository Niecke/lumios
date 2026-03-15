# ---- Stage 1: Build ----
FROM docker.io/library/node:24-alpine AS builder

ARG VITE_GOOGLE_CLIENT_ID

WORKDIR /build

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build


# ---- Stage 2: Runtime ----
FROM docker.io/library/nginx:1.29-alpine

COPY --from=builder /build/dist /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

EXPOSE 8080
