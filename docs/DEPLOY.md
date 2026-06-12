# Deploying Harnext (single-node VPS)

The stack runs as Docker containers behind a shared nginx reverse proxy.

```
                       ┌───────────────── reverse-proxy (nginx) ─────────────────┐
  app.harnext.dev ──TLS──►  / → web:3100   /api → ingest:8000   /mcp → mcp:8765
                       └──────────────────────────────────────────────────────────┘
                                          │ (docker network: reverse-proxy)
   redpanda ◄── ingest ─┬─ classifier ─┬─ builder ──(Claude CLI, git AgentFS)
                        └──────────────┴─ mcp           shared volume: sqlite + agentfs
```

- **One Python image** (`harnext-py`) runs all four services (ingest / classifier /
  builder / mcp) — same image, different `command:`.
- **AgentFS `git` backend** — one git repo per org, snapshots = commits. No FUSE, no
  privileged containers.
- **Harness auth** — the builder/mcp run the Claude CLI authenticated by your account's
  OAuth token (`~/.claude/.credentials.json`), seeded into the containers. No API key.
  Services run as a non-root `app` user (Claude refuses `--dangerously-skip-permissions`
  as root).

## Prerequisites on the VPS

- Docker + Docker Compose v2.
- The shared reverse proxy running, with its external network:
  `docker network create reverse-proxy` (already done if the proxy is up).
- DNS: an **A record** `app.harnext.dev → <VPS IPv4>` (and optionally an AAAA to
  the VPS IPv6). Required before issuing the TLS cert.

## 1. Get the code + images onto the VPS

```bash
# code
rsync -az --exclude .git --exclude '**/node_modules' --exclude '**/.venv' \
  --exclude '**/.next' --exclude data ./ deployer@VPS:~/projects/harnext/
```

Build the images **on the VPS** (the Python build is light; the Next build is not — if
RAM is tight, build the web image locally and ship it):

```bash
# on the VPS
cd ~/projects/harnext
docker build -f infra/docker/Dockerfile.python -t harnext-py:latest .
docker build -f apps/web/Dockerfile           -t harnext-web:latest .
# …or ship a locally-built image:  docker save img | gzip | ssh VPS 'docker load'
```

## 2. Configure

```bash
cp .env.production.example .env
sed -i "s|^JWT_SECRET=.*|JWT_SECRET=$(openssl rand -hex 32)|" .env   # strong secret
# URLs in .env already point at https://app.harnext.dev

# Claude credentials (your ~/.claude/.credentials.json) — never commit this.
mkdir -p secrets
scp ~/.claude/.credentials.json deployer@VPS:~/projects/harnext/secrets/claude-credentials.json
chmod 600 secrets/claude-credentials.json
```

## 3. Run

```bash
docker compose -f docker-compose.prod.yml up -d --no-build
docker compose -f docker-compose.prod.yml ps         # all healthy
# loopback debug ports: web :13100, ingest :18000, mcp :18765
curl -s localhost:18000/health
```

## 4. Reverse proxy + TLS

```bash
RP=~/projects/vps-shared-reverse-proxy

# (a) HTTP bootstrap so certbot can solve the ACME challenge
cp infra/docker/nginx/app.harnext.dev.http.conf $RP/nginx/conf.d/harnext.conf
docker exec reverse-proxy-nginx nginx -t && docker exec reverse-proxy-nginx nginx -s reload

# (b) issue the cert (needs DNS pointing at this VPS)
cd $RP && docker compose run --rm certbot certonly --webroot -w /var/www/certbot \
  -d app.harnext.dev --email you@harnext.dev --agree-tos --no-eff-email

# (c) swap to the HTTPS config and reload
cp ~/projects/harnext/infra/docker/nginx/app.harnext.dev.conf \
   $RP/nginx/conf.d/harnext.conf
docker exec reverse-proxy-nginx nginx -t && docker exec reverse-proxy-nginx nginx -s reload
```

Visit https://app.harnext.dev — register, create a project, connect a source,
and connect a harness from the **Connect** panel (one `claude mcp add … --header
"Authorization: Bearer …"`).

## Operations

```bash
docker compose -f docker-compose.prod.yml logs -f builder      # follow a service
docker compose -f docker-compose.prod.yml restart mcp
docker compose -f docker-compose.prod.yml pull && … up -d      # update images
```

- **Data** lives in the `mg_data` volume (`/app/data`: `harnext.sqlite` + `agentfs/`).
  Back it up with `docker run --rm -v harnext_mg_data:/d -v $PWD:/b alpine tar czf /b/mg_data.tgz -C /d .`.
- **Rotate the Claude token**: replace `secrets/claude-credentials.json`, then
  `docker compose … up -d --force-recreate builder mcp` (re-seeds `~/.claude`).
- **Revoke all MCP/session tokens**: change `JWT_SECRET` and recreate `ingest`.
