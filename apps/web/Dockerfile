# Next.js 15 (standalone) production image for the dashboard.
#
# Build from the repo root (needs the pnpm workspace files):
#   docker build -f apps/web/Dockerfile -t meaninggrid-web .
#
# The client calls the API/MCP through the reverse proxy on the SAME origin, so
# the image is domain-agnostic: NEXT_PUBLIC_API_BASE_URL defaults to the
# relative "/api". Override it as a build-arg for split-host setups.

# ---- build stage -----------------------------------------------------------
FROM node:20-slim AS build
WORKDIR /app
RUN npm install -g pnpm@9.12.0

# Install deps from the lockfile (workspace = just apps/web).
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json ./apps/web/package.json
RUN pnpm install --frozen-lockfile

# Build the standalone server.
COPY apps/web ./apps/web
ARG NEXT_PUBLIC_API_BASE_URL=/api
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL} \
    NEXT_TELEMETRY_DISABLED=1
RUN pnpm --filter @meaninggrid/web build

# ---- runtime stage ---------------------------------------------------------
FROM node:20-slim AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3100 \
    HOSTNAME=0.0.0.0

# standalone bundle mirrors the monorepo layout (apps/web/server.js + node_modules)
COPY --from=build /app/apps/web/.next/standalone ./
COPY --from=build /app/apps/web/.next/static ./apps/web/.next/static

EXPOSE 3100
CMD ["node", "apps/web/server.js"]
