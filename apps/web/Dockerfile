FROM node:22-alpine AS build
WORKDIR /web
COPY apps/web/package*.json ./
RUN npm ci
COPY apps/web/ ./
ARG SIMULATOR
ENV VITE_SIMULATOR=$SIMULATOR
RUN npm run build
FROM nginxinc/nginx-unprivileged:1.28-alpine
COPY --from=build /web/dist /usr/share/nginx/html
COPY deploy/nginx.conf.template /etc/nginx/templates/default.conf.template
ENV API_UPSTREAM=http://api:8000
EXPOSE 8080
