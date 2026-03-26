FROM docker.io/library/nginx:1.29-alpine

ARG APP_URL=https://lumios-app.niecke-it.de
ARG BACKEND_URL=https://lumios-api.niecke-it.de

# Expose BACKEND_URL at runtime so nginx envsubst can use it in the CSP header
ENV BACKEND_URL=${BACKEND_URL}

COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY src/ /usr/share/nginx/html/

# Replace placeholders with actual URLs in static files
RUN sed -i "s|%%APP_URL%%|${APP_URL}|g" /usr/share/nginx/html/index.html && \
    sed -i "s|%%APP_URL%%|${APP_URL}|g" /usr/share/nginx/html/registration.js && \
    sed -i "s|%%BACKEND_URL%%|${BACKEND_URL}|g" /usr/share/nginx/html/registration.js

EXPOSE 8080
