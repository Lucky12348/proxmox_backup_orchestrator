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
APP_MAINTENANCE_AGENT_SERVICE=proxmox-backup-orchestrator-app-maintenance-agent.service
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
  python -c "import json, os; print(json.dumps({'NOTIFICATIONS_ENABLED': os.getenv('NOTIFICATIONS_ENABLED'), 'NTFY_BASE_URL': os.getenv('NTFY_BASE_URL'), 'NTFY_USERNAME': os.getenv('NTFY_USERNAME'), 'NTFY_TOPIC_SET': bool(os.getenv('NTFY_TOPIC')), 'NTFY_TOPIC_IS_DEFAULT': os.getenv('NTFY_TOPIC') == 'proxmox-backup-orchestrator'}))"
systemd-run --on-active=10 --unit pbo-app-maintenance-agent-restart \
  systemctl restart proxmox-backup-orchestrator-app-maintenance-agent.service
```

If `docker-compose` is not available, the agent falls back to `docker compose` with the same `--env-file .env` arguments.

The command working directory is always `APP_REPO_PATH`. The production `.env` must exist at `APP_REPO_PATH/.env`; otherwise the update fails before `git pull` with:

```text
.env not found at APP_REPO_PATH
```

The post-update verification compares non-secret values from `.env` with the recreated API container. It checks `NOTIFICATIONS_ENABLED`, `NTFY_BASE_URL`, `NTFY_USERNAME`, and whether `NTFY_TOPIC` is set and not the default placeholder. It does not print `NTFY_PASSWORD`, the topic value, tokens, or other secrets. If the API container falls back to Compose defaults while `.env` contains production values, the update is marked failed.

Because the app maintenance agent runs outside Docker, a code update can change the agent itself while the old process is still serving the current request. The update flow schedules a delayed systemd restart of `APP_MAINTENANCE_AGENT_SERVICE` after the container update and verification. If this is the first deployment of the fixed agent code, restart the service manually or run:

```bash
scripts/deploy-app-vm.sh
```

That script runs `git pull`, restarts the app maintenance agent, then recreates Docker containers with `docker-compose --env-file .env -f infra/docker/docker-compose.yml up --build -d`.

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

If the pull succeeds, the agent then schedules a restart of its own HTTP
service (`AGENT_HTTP_SERVICE_NAME`) via `systemd-run --on-active=10 ...
systemctl restart <service>` (or `systemctl try-restart ... --no-block` if
`systemd-run` is unavailable) — the same delayed self-restart pattern the App
VM maintenance agent already uses for itself. The restart is delayed a few
seconds because the request handling the update is itself running inside the
process being restarted. If `AGENT_HTTP_SERVICE_NAME` is not set, the pull
still succeeds but the update is reported as failed with a clear message that
the service needs a manual restart — the "Tout mettre à jour" click alone is
not enough in that case.

Configure each agent `.env` with:

```env
AGENT_REPO_PATH=/opt/proxmox-backup-orchestrator-agent-repo
AGENT_MAINTENANCE_TIMEOUT_SECONDS=120
AGENT_HTTP_SERVICE_NAME=proxmox-backup-orchestrator-agent-http.service
```

Use `/opt/proxmox-backup-orchestrator-pbs-agent-repo` and
`proxmox-backup-orchestrator-pbs-agent-http.service` for the PBS VM agent.

### `AGENT_REPO_PATH` must be a real git checkout

`git pull` only does something useful if `AGENT_REPO_PATH` is an actual git
repository tracking this project's remote. A directory populated by copying
files (`scp`/`rsync`) has no `.git`, so every maintenance update silently
fails at `git fetch` — the agent keeps running whatever code was last copied
onto it, no matter how many times "Tout mettre à jour" is clicked.

One-time setup per machine (host agent and PBS agent), so the existing
`.venv` and systemd units never have to move:

```bash
# 1. Full clone of the monorepo next to the existing agent directory.
git clone git@github.com:<you>/proxmox_backup_orchestrator.git /opt/proxmox-backup-orchestrator-agent-repo

# 2. Point the running agent's src/tests at the clone via symlinks, replacing
#    the plain directories that were there before (back them up first if
#    unsure). The .venv and systemd unit paths are untouched.
rm -rf /opt/proxmox-backup-orchestrator-agent/src /opt/proxmox-backup-orchestrator-agent/tests
ln -s /opt/proxmox-backup-orchestrator-agent-repo/apps/agent/src   /opt/proxmox-backup-orchestrator-agent/src
ln -s /opt/proxmox-backup-orchestrator-agent-repo/apps/agent/tests /opt/proxmox-backup-orchestrator-agent/tests

# 3. Set AGENT_REPO_PATH and AGENT_HTTP_SERVICE_NAME in the agent's .env (see
#    above), then restart the HTTP service once by hand to pick up the .env
#    change.
systemctl restart proxmox-backup-orchestrator-agent-http.service
```

Repeat with `-pbs-agent`/`-pbs-agent-repo` paths on the PBS VM. After this
one-time setup, `git pull` in `AGENT_REPO_PATH` updates `apps/agent/src`
through the symlink, and the maintenance flow's own restart step reloads it —
no more manual `scp` + `systemctl restart` per update.
