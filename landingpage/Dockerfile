FROM docker.io/library/nginx:1.29-alpine

ARG APP_URL=https://lumios-app.niecke-it.de

COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY src/ /usr/share/nginx/html/

# Replace placeholder with actual app URL
RUN sed -i "s|%%APP_URL%%|${APP_URL}|g" /usr/share/nginx/html/index.html

EXPOSE 8080
