FROM docker.io/library/nginx:1.31.8-alpine@sha256:1ef7ca94d7879df82421428ce13bd1eaa412404953859cf7a5b6512c25e67a60

ARG GIT_SHA=dev
ARG BUILD_TIMESTAMP=unknown
ENV GIT_SHA=${GIT_SHA}
ENV BUILD_TIMESTAMP=${BUILD_TIMESTAMP}

ENV APP_URL=https://lumios-app.niecke-it.de
ENV BACKEND_URL=https://lumios-api.niecke-it.de

COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY src/ /usr/share/nginx/html/
COPY substitute-env.sh /docker-entrypoint.d/40-substitute-env.sh
RUN chmod +x /docker-entrypoint.d/40-substitute-env.sh

EXPOSE 8080
