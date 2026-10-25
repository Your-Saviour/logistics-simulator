FROM node:22-alpine AS build
WORKDIR /web
COPY apps/twin/web/package*.json ./
RUN npm ci
COPY apps/twin/web/ ./
COPY contracts/handling/v1/facility.json /contracts/handling/v1/facility.json
COPY contracts/fleet/v1/navigation.json /contracts/fleet/v1/navigation.json
RUN npm run build
FROM nginxinc/nginx-unprivileged:1.28-alpine
COPY --from=build /web/dist /usr/share/nginx/html
COPY deploy/nginx.conf.template /etc/nginx/templates/default.conf.template
ENV API_UPSTREAM=http://twin-api:8000
EXPOSE 8080
