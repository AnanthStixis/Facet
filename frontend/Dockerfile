# Facet frontend — built as static assets, served by nginx.
#
# nginx proxies /api and /health onto the backend container so the browser
# still sees one origin — the refresh cookie is SameSite=Strict and relies on
# frontend and API sharing an origin, exactly as vite.config.ts's dev proxy
# does locally. Do not serve this behind a separate API domain without also
# relaxing that cookie setting.

FROM node:20-slim AS builder

WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build


FROM nginx:1.27-alpine AS runtime

COPY --from=builder /build/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -q -O- http://localhost/ >/dev/null || exit 1
