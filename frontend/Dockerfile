# syntax=docker/dockerfile:1
FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=secret,id=extra_ca,required=false if [ -s /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca NODE_EXTRA_CA_CERTS=/run/secrets/extra_ca SSL_CERT_FILE=/run/secrets/extra_ca; fi; npm ci --no-audit --no-fund

FROM node:22-alpine AS build
WORKDIR /app
# Rewrites to the API are resolved at build time.
ARG BACKEND_URL=http://api:8000
ENV BACKEND_URL=$BACKEND_URL NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS run
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN addgroup -S app && adduser -S app -G app
COPY --from=build --chown=app:app /app/.next/standalone ./
COPY --from=build --chown=app:app /app/.next/static ./.next/static
USER app
EXPOSE 3000
CMD ["node", "server.js"]
