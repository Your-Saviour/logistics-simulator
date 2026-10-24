FROM node:24.13.0-alpine
RUN apk add --no-cache chromium
WORKDIR /checks
COPY apps/browser-check/package*.json ./
RUN npm ci
COPY apps/browser-check/playwright.config.ts ./
COPY apps/browser-check/stacks.spec.ts apps/browser-check/twin.spec.ts ./
CMD ["npx","playwright","test"]
