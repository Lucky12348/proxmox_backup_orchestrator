# Maintenance / Updates

The Settings page includes a controlled update center for the app VM, the Proxmox host agent, and the PBS VM agent.

## Security Model

- UI maintenance endpoints are under the authenticated `/api/v1` router.
- Agent maintenance endpoints require the existing `X-Agent-Token` header.
- The API and agents run fixed command lists only. They do not accept arbitrary shell commands from the browser.
- Logs are returned with common token, secret, password, key, and authorization patterns masked.
- Every command has a timeout.

## App VM Maintenance Agent

The API container does not run App VM Git or Docker commands directly. It calls a local App VM maintenance agent instead.

The agent binds to `127.0.0.1:8092` by default and requires `X-Agent-Token`.

Configure the App VM `.env`:

```env
APP_MAINTENANCE_AGENT_BASE_URL=http://host.docker.internal:8092
APP_MAINTENANCE_AGENT_HOST=127.0.0.1
APP_MAINTENANCE_AGENT_PORT=8092
APP_MAINTENANCE_AGENT_TOKEN=<random>
APP_REPO_PATH=/opt/proxmox_backup_orchestrator
APP_COMPOSE_FILE=infra/docker/docker-compose.yml
APP_MAINTENANCE_TIMEOUT_SECONDS=300
MAINTENANCE_TIMEOUT_SECONDS=300
```

`APP_MAINTENANCE_AGENT_BASE_URL` uses `host.docker.internal` for the API container. If the API runs directly on the host, use `http://127.0.0.1:8092`.

Install the systemd service:

```bash
cd /opt/proxmox_backup_orchestrator/apps/app-maintenance-agent
python3 -m venv .venv
.venv/bin/pip install -e .
cp deploy/systemd/proxmox-backup-orchestrator-app-maintenance-agent.service \
  /etc/systemd/system/proxmox-backup-orchestrator-app-maintenance-agent.service
systemctl daemon-reload
systemctl enable --now proxmox-backup-orchestrator-app-maintenance-agent.service
```

The app maintenance agent uses `APP_REPO_PATH` and runs:

```bash
test -f .env
docker-compose --env-file .env -f infra/docker/docker-compose.yml config --quiet
git fetch
git status --short
git rev-parse --abbrev-ref HEAD
git rev-parse HEAD
git rev-parse @{u}
git pull --ff-only
docker-compose --env-file .env -f infra/docker/docker-compose.yml up --build -d
docker-compose --env-file .env -f infra/docker/docker-compose.yml exec -T api \
  python -c "import os; print(os.getenv('NOTIFICATIONS_ENABLED'), os.getenv('NTFY_BASE_URL'))"
```

If `docker-compose` is not available, the agent falls back to `docker compose` with the same `--env-file .env` arguments.

The command working directory is always `APP_REPO_PATH`. The production `.env` must exist at `APP_REPO_PATH/.env`; otherwise the update fails before `git pull` with:

```text
.env not found at APP_REPO_PATH
```

The post-update verification prints only `NOTIFICATIONS_ENABLED` and `NTFY_BASE_URL` from inside the recreated API container. It does not print `NTFY_PASSWORD`, `NTFY_TOPIC`, tokens, or other secrets.

Updating the app VM can rebuild containers and restart the Web UI.

## Agent Updates

Each agent uses `AGENT_REPO_PATH` and runs:

```bash
git fetch
git status --short
git rev-parse HEAD
git rev-parse @{u}
git pull --ff-only
```

Configure each agent `.env` with:

```env
AGENT_REPO_PATH=/opt/proxmox-backup-orchestrator-agent
AGENT_MAINTENANCE_TIMEOUT_SECONDS=120
```

Use `/opt/proxmox-backup-orchestrator-pbs-agent` for the PBS VM agent.
