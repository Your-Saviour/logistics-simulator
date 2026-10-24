FROM node:24.13.0-alpine
RUN apk add --no-cache chromium && npm install --prefix /opt/browser playwright@1.58.2
WORKDIR /tests
COPY ui.mjs .
CMD ["node", "ui.mjs"]
