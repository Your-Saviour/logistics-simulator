FROM node:24-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
ENV NODE_OPTIONS=--max-old-space-size=512
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY . .
RUN npm test && npm run build
FROM nginx:1.30.6-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY default.conf.template /etc/nginx/templates/default.conf.template
ENV API_UPSTREAM=storage-api:8000
EXPOSE 80
