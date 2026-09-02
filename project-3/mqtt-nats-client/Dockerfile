FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY index.html app.js nats-app.js style.css /usr/share/nginx/html/
# JS biblioteke su ugrađene u image (ne učitavaju se sa CDN-a u toku rada),
# da demonstracija radi i bez pristupa internetu
COPY vendor/ /usr/share/nginx/html/vendor/
EXPOSE 80
