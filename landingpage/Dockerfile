FROM docker.io/library/nginx:1.29-alpine

ARG APP_URL=https://app.lumios.niecke-it.de

COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY index.html /usr/share/nginx/html/index.html
COPY impressum.html /usr/share/nginx/html/impressum.html
COPY style.css /usr/share/nginx/html/style.css
COPY favicon.ico /usr/share/nginx/html/favicon.ico
COPY favicon-16x16.png /usr/share/nginx/html/favicon-16x16.png
COPY favicon-32x32.png /usr/share/nginx/html/favicon-32x32.png

# Replace placeholder with actual app URL
RUN sed -i "s|%%APP_URL%%|${APP_URL}|g" /usr/share/nginx/html/index.html

EXPOSE 8080
