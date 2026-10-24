FROM node:24.13.0-alpine AS build
WORKDIR /src
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm test && npm run check && npm run build
FROM nginx:1.28.2-alpine
COPY nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /src/dist /usr/share/nginx/html
ENV API_UPSTREAM=logistics-api:8000
EXPOSE 80
