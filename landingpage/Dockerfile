FROM docker.io/library/nginx:1.31-alpine@sha256:72ba65eb42c10344912a84ff42408db7d34f2feb642204570ab8fc5ffd29f1d3

ARG APP_URL=https://lumios-app.niecke-it.de
ARG BACKEND_URL=https://lumios-api.niecke-it.de

ENV APP_URL=${APP_URL}
ENV BACKEND_URL=${BACKEND_URL}

COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY src/ /usr/share/nginx/html/
COPY substitute-env.sh /docker-entrypoint.d/40-substitute-env.sh
RUN chmod +x /docker-entrypoint.d/40-substitute-env.sh

EXPOSE 8080
