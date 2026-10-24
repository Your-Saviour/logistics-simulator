FROM node:24-alpine AS build
WORKDIR /build
COPY apps/manufacturing/frontend/package*.json ./
RUN npm ci
COPY apps/manufacturing/frontend/angular.json apps/manufacturing/frontend/tsconfig.json ./
COPY apps/manufacturing/frontend/src ./src
RUN npm test && npm run build
FROM nginx:1.30.6-alpine
COPY --from=build /build/dist/manufacturing/browser /usr/share/nginx/html
COPY apps/manufacturing/frontend/default.conf.template /etc/nginx/templates/default.conf.template
ENV API_UPSTREAM=manufacturing-api:8000
EXPOSE 80
