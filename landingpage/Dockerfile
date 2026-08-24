FROM docker.io/library/nginx:1.31-alpine@sha256:db35bfc6b2951e7f8a72db5db120288c127ffaeeb4a6d4b95a26fead017d5913

ARG APP_URL=https://lumios-app.niecke-it.de
ARG BACKEND_URL=https://lumios-api.niecke-it.de

ENV APP_URL=${APP_URL}
ENV BACKEND_URL=${BACKEND_URL}

COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY src/ /usr/share/nginx/html/
COPY substitute-env.sh /docker-entrypoint.d/40-substitute-env.sh
RUN chmod +x /docker-entrypoint.d/40-substitute-env.sh

EXPOSE 8080
