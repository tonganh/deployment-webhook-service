# Deployment Webhook Service - Technical Requirements

## Problem Statement

Current CI/CD uses SSH keys in GitHub Actions, creating security risk: anyone with repo write access can modify workflow and execute arbitrary commands on production server.

## Solution

Isolated Docker container that receives webhook requests, validates tokens, and executes predefined deployment commands. Builds remain on server for speed.

## Architecture

```
GitHub Actions → Webhook POST → Deployment Container → 
  ├─ Token validation (HMAC)
  ├─ git pull (mounted volume)
  └─ docker compose up --build (Docker socket)
```

## Components

- **Webhook Service**: Python HTTP server (port 9000)
- **Container**: Isolated from app, mounts app directory + Docker socket
- **Security**: Token-based auth, predefined commands only

## Setup Requirements

### 1. Container Setup

```bash
# Required files
- Dockerfile (Python 3.11-alpine + docker-cli-compose)
- deployment-service.py (webhook handler)
- docker-compose.yml
```

### 2. Environment Variables

- `DEPLOY_WEBHOOK_SECRET`: Secure token (generate with `openssl rand -hex 32`)
- `APP_PATH`: Absolute path to application directory
- `COMPOSE_FILE`: Docker compose file name (default: `docker-compose.prod.yml`)

### 3. Volume Mounts

- App directory: Read-write access for `git pull`
- Docker socket: `/var/run/docker.sock` for `docker compose` commands

### 4. GitHub Actions Integration

**Required Secrets:**
- `DEPLOY_WEBHOOK_URL`: `http://server:9000` or HTTPS endpoint
- `DEPLOY_WEBHOOK_TOKEN`: Same value as `DEPLOY_WEBHOOK_SECRET`

**Workflow Pattern:**
```yaml
- name: Trigger deployment
  run: |
    curl -X POST ${{ secrets.DEPLOY_WEBHOOK_URL }}/deploy \
      -H "Authorization: Bearer ${{ secrets.DEPLOY_WEBHOOK_TOKEN }}" \
      -H "Content-Type: application/json" \
      -d '{"action": "deploy", "commit": "${{ github.sha }}"}'
```

## Security Requirements

1. **Token Validation**: HMAC comparison on all requests
2. **Command Whitelist**: Only execute `git pull` and `docker compose up --build -d`
3. **Health Endpoint**: `/health` for monitoring (no auth required)
4. **Logging**: All deployment attempts logged with IP addresses
5. **Error Handling**: Timeout protection (60s git, 600s build)

## Deployment Flow

1. CI runs tests/lint/build validation
2. On success, POST to `/deploy` with token
3. Container validates token
4. Executes: `cd $APP_PATH && git pull origin main`
5. Executes: `cd $APP_PATH && docker compose -f $COMPOSE_FILE up --build -d`
6. Returns success/failure status

## Optional Enhancements

- Rate limiting (prevent webhook spam)
- GitHub webhook signature validation
- Deployment queue (prevent concurrent builds)
- Nginx reverse proxy for HTTPS
- Slack/email notifications on deploy

## Testing

```bash
# Health check
curl http://localhost:9000/health

# Test deployment (replace TOKEN)
curl -X POST http://localhost:9000/deploy \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action": "deploy", "commit": "test"}'
```
