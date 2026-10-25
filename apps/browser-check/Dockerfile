FROM node:24.13.0-bookworm-slim
WORKDIR /checks
COPY apps/browser-check/package*.json ./
RUN npm ci && npx playwright install --with-deps --only-shell chromium && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/* /root/.npm
COPY apps/browser-check/playwright.config.ts ./
COPY apps/browser-check/stacks.spec.ts apps/browser-check/twin.spec.ts apps/browser-check/runtime.spec.ts apps/browser-check/handling-scene.spec.ts ./
COPY contracts/handling/v1/facility.json ./facility.json
CMD ["npx","playwright","test"]
