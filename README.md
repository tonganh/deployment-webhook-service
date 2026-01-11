# Deployment Webhook Service

A secure Python webhook service that receives deployment requests, validates tokens, and executes configurable deployment commands directly on the server.

## Quick Start

1. **Install Python 3.11+ and create virtual environment:**
```bash
python3 --version
python3 -m venv .venv
source .venv/bin/activate
```

2. **Install dependencies (if any):**
```bash
pip install -r requirements.txt
```

**Note:** This project uses only Python standard library, so no additional packages are required. The requirements.txt is kept for future dependencies.

3. **Generate a secure token:**
```bash
openssl rand -hex 32
```

4. **Set environment variables:**
```bash
export DEPLOY_WEBHOOK_SECRET="your-secret-token-here"
export PORT=9000
export COMMAND_TIMEOUT=600
```

**Note:** You can deploy multiple projects from different locations. Just include `cd` in your command to specify the directory.

5. **Run the service:**
```bash
source .venv/bin/activate
python3 deployment-service.py
```

Or run as a background process:
```bash
source .venv/bin/activate
nohup python3 deployment-service.py > deployment.log 2>&1 &
```

**Virtual Environment Benefits:**
- Isolates dependencies from system Python
- Prevents conflicts with other projects
- Easy to recreate on different servers
- Can be version controlled (exclude .venv in .gitignore)

## Configuration

### Environment Variables

- `DEPLOY_WEBHOOK_SECRET` (required): Secure token for authentication
- `PORT` (optional): Port to listen on (default: 9000)
- `COMMAND_TIMEOUT` (optional): Command timeout in seconds (default: 600)

**Multiple Projects Support:**
- You can deploy multiple projects from different locations on your server
- Include `cd /path/to/project` in your command to specify the directory
- Each deployment request can target a different project location

### Command Security

Commands are sent in the request payload and validated for security. Only the following are allowed:

**Allowed Commands:**
- `cd` - Change directory
- `git` - Git commands (pull, fetch, checkout, etc.)
- `docker` - Docker commands (compose, build, up, down, etc.)

**Blocked Commands:**
- `rm` - Remove/delete commands
- `delete`, `format`, `dd`, `mkfs` - Dangerous system commands
- Commands that pipe to shell (`| sh`, `| bash`)
- Commands redirecting to `/dev/`

**Command Examples for Different Projects:**

**Project 1 (in /var/www/project1):**
```json
{
  "command": "cd /var/www/project1 && git pull origin master && docker compose up -d --build"
}
```

**Project 2 (in /home/user/project2):**
```json
{
  "command": "cd /home/user/project2 && git pull origin release && docker compose -f docker-compose.staging.yml up -d --build"
}
```

**Project 3 (in /opt/apps/project3):**
```json
{
  "command": "cd /opt/apps/project3 && git pull origin main && docker compose up -d --build"
}
```

**Note:** Always include `cd /path/to/project` at the beginning of your command to specify which project directory to use.

## Systemd Service (Recommended)

1. **Create service file:**
```bash
sudo nano /etc/systemd/system/deployment-webhook.service
```

2. **Add the following content:**
```ini
[Unit]
Description=Deployment Webhook Service
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/path/to/deploy-webhook
Environment="DEPLOY_WEBHOOK_SECRET=your-secret-token"
Environment="PORT=9000"
Environment="COMMAND_TIMEOUT=600"
ExecStart=/path/to/deploy-webhook/.venv/bin/python3 /path/to/deploy-webhook/deployment-service.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**Important:** Make sure to:
- Replace `/path/to/deploy-webhook` with your actual project directory
- Use the full path to the virtual environment's Python: `.venv/bin/python3`
- Ensure the virtual environment is created before starting the service

3. **Enable and start the service:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable deployment-webhook
sudo systemctl start deployment-webhook
sudo systemctl status deployment-webhook
```

## Testing

**Health check:**
```bash
curl http://localhost:9000/health
```

**Test deployment (replace TOKEN with your secret and PATH with your project path):**
```bash
curl -X POST http://localhost:9000/deploy \
  -H "Authorization: Bearer TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"action": "deploy", "commit": "test", "command": "cd /var/www/myapp && git pull origin master && docker compose up -d --build"}'
```

## GitHub Actions Integration

Add these secrets to your GitHub repository:

- `DEPLOY_WEBHOOK_URL`: `http://your-server:9000` or HTTPS endpoint
- `DEPLOY_WEBHOOK_TOKEN`: Same value as `DEPLOY_WEBHOOK_SECRET`

**Workflow example (single project):**
```yaml
- name: Trigger deployment
  run: |
    curl -X POST ${{ secrets.DEPLOY_WEBHOOK_URL }}/deploy \
      -H "Authorization: Bearer ${{ secrets.DEPLOY_WEBHOOK_TOKEN }}" \
      -H "Content-Type: application/json" \
      -d '{"action": "deploy", "commit": "${{ github.sha }}", "command": "cd /var/www/myapp && git pull origin master && docker compose up -d --build"}'
```

**Multiple projects example:**
```yaml
- name: Deploy Project 1
  if: github.repository == 'myorg/project1'
  run: |
    curl -X POST ${{ secrets.DEPLOY_WEBHOOK_URL }}/deploy \
      -H "Authorization: Bearer ${{ secrets.DEPLOY_WEBHOOK_TOKEN }}" \
      -H "Content-Type: application/json" \
      -d '{"action": "deploy", "commit": "${{ github.sha }}", "command": "cd /var/www/project1 && git pull origin master && docker compose up -d --build"}'

- name: Deploy Project 2
  if: github.repository == 'myorg/project2'
  run: |
    curl -X POST ${{ secrets.DEPLOY_WEBHOOK_URL }}/deploy \
      -H "Authorization: Bearer ${{ secrets.DEPLOY_WEBHOOK_TOKEN }}" \
      -H "Content-Type: application/json" \
      -d '{"action": "deploy", "commit": "${{ github.sha }}", "command": "cd /home/user/project2 && git pull origin release && docker compose -f docker-compose.staging.yml up -d --build"}'
```

**Different branches for same project:**
```yaml
- name: Deploy to production
  if: github.ref == 'refs/heads/master'
  run: |
    curl -X POST ${{ secrets.DEPLOY_WEBHOOK_URL }}/deploy \
      -H "Authorization: Bearer ${{ secrets.DEPLOY_WEBHOOK_TOKEN }}" \
      -H "Content-Type: application/json" \
      -d '{"action": "deploy", "commit": "${{ github.sha }}", "command": "cd /var/www/myapp && git pull origin master && docker compose up -d --build"}'

- name: Deploy to staging
  if: github.ref == 'refs/heads/release'
  run: |
    curl -X POST ${{ secrets.DEPLOY_WEBHOOK_URL }}/deploy \
      -H "Authorization: Bearer ${{ secrets.DEPLOY_WEBHOOK_TOKEN }}" \
      -H "Content-Type: application/json" \
      -d '{"action": "deploy", "commit": "${{ github.sha }}", "command": "cd /var/www/myapp && git pull origin release && docker compose -f docker-compose.staging.yml up -d --build"}'
```

## Security Features

- Token-based authentication using HMAC comparison
- Command whitelist validation (only allows cd, git, docker commands)
- Dangerous command blocking (rm, delete, format, etc.)
- Request logging with IP addresses
- Timeout protection (configurable, default 600s)
- Runs directly on server (no container overhead)

## Architecture

```
GitHub Actions → Webhook POST (with command) → Python Service → 
  ├─ Token validation (HMAC)
  ├─ Command validation (whitelist check)
  ├─ Execute command (with cd for directory changes)
  └─ Return success/failure status
```

## Virtual Environment Setup

### Creating Virtual Environment

```bash
# Create virtual environment
python3 -m venv .venv

# Activate virtual environment (Linux/macOS)
source .venv/bin/activate

# Activate virtual environment (Windows)
.venv\Scripts\activate
```

### Deactivating Virtual Environment

```bash
deactivate
```

### Recreating Virtual Environment

If you need to recreate the environment on a new server:

```bash
# Remove old virtual environment
rm -rf .venv

# Create new virtual environment
python3 -m venv .venv

# Activate it
source .venv/bin/activate

# Install dependencies (if any are added in the future)
pip install -r requirements.txt
```

### Using Virtual Environment in Scripts

For automated deployments or scripts, always activate the venv first:

```bash
#!/bin/bash
cd /path/to/deploy-webhook
source .venv/bin/activate
python3 deployment-service.py
```

## Logs

View service logs:
```bash
# If running with systemd
sudo journalctl -u deployment-webhook -f

# If running with nohup
tail -f deployment.log
```
