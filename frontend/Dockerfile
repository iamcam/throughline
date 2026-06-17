# frontend/Dockerfile
FROM node:20-alpine AS builder
WORKDIR /app

COPY frontend/package.json frontend/yarn.lock ./
RUN yarn install --frozen-lockfile

COPY frontend/ .
RUN yarn build

FROM caddy:2-alpine
COPY --from=builder /app/dist /srv
COPY infra/Caddyfile /etc/caddy/Caddyfile

EXPOSE 80
EXPOSE 443