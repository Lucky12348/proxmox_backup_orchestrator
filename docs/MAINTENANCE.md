# Maintenance / Updates

The Settings page includes a controlled update center for the app VM, the Proxmox host agent, and the PBS VM agent.

## Security Model

- UI maintenance endpoints are under the authenticated `/api/v1` router.
- Agent maintenance endpoints require the existing `X-Agent-Token` header.
- The API and agents run fixed command lists only. They do not accept arbitrary shell commands from the browser.
- Logs are returned with common token, secret, password, key, and authorization patterns masked.
- Every command has a timeout.

## App VM Update

The app VM update runner uses `APP_REPO_PATH` and runs:

```bash
git fetch
git status --short
git rev-parse HEAD
git rev-parse @{u}
git pull --ff-only
docker-compose -f infra/docker/docker-compose.yml up --build -d
```

If `docker-compose` is not available, the API falls back to `docker compose`.

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
