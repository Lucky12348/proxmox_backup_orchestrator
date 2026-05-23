# Installation

This guide installs the production layout:

- app VM `backupOrchestrator` running Docker Compose: API, Web UI, Postgres
- Proxmox host root agent on port `8090`
- PBS VM root agent on port `8091`
- external USB disk passed from Proxmox host to PBS VM

Do not use `code_secret`. Use strong random values from `openssl rand -hex 32`.

## 1. Prerequisites

- A Proxmox host with firewall enabled.
- A PBS VM running on that Proxmox host.
- An app VM named `backupOrchestrator` with Docker and Docker Compose.
- A dedicated external USB disk for removable PBS backups.
- Network reachability:
  - app VM to Proxmox API `8006`
  - app VM to PBS API `8007`
  - app VM to host agent `8090`
  - app VM to PBS agent `8091`

Record these values before installation:

```text
APP_VM_IP=
PROXMOX_HOST_IP=
PBS_VM_IP=
PBS_VM_ID=
PVE_NODE_NAME=
MAIN_PBS_DATASTORE=backup-store
```

## 2. Install the App VM

Clone the repository on `backupOrchestrator`:

```bash
git clone <repo-url> /opt/proxmox_backup_orchestrator
cd /opt/proxmox_backup_orchestrator
cp .env.example .env
chmod 600 .env
```

Edit `.env` and keep only the app VM values active for Docker Compose. Required app variables:

```env
APP_ENV=production
API_PORT=8000
WEB_PORT=5173
WEB_ALLOWED_HOSTS=extbackup.sofianechaoui.fr,localhost,127.0.0.1,192.168.1.103
FRONTEND_ORIGIN=http://<app-vm-ip>:5173
FRONTEND_ORIGIN_ALT=http://<app-vm-ip>
AUTO_SYNC_ENABLED=true
PROXMOX_SYNC_INTERVAL_SECONDS=60
PBS_SYNC_INTERVAL_SECONDS=60
MAINTENANCE_TIMEOUT_SECONDS=300
APP_MAINTENANCE_AGENT_BASE_URL=http://host.docker.internal:8092
APP_MAINTENANCE_AGENT_HOST=127.0.0.1
APP_MAINTENANCE_AGENT_PORT=8092
APP_MAINTENANCE_AGENT_TOKEN=<app-maintenance-agent-token>
APP_REPO_PATH=/opt/proxmox_backup_orchestrator
APP_COMPOSE_FILE=infra/docker/docker-compose.yml
APP_MAINTENANCE_TIMEOUT_SECONDS=300

POSTGRES_DB=proxmox_backup_orchestrator
POSTGRES_USER=pbo
POSTGRES_PASSWORD=<random>
DATABASE_URL=postgresql+psycopg://pbo:<random>@db:5432/proxmox_backup_orchestrator

AUTH_ENABLED=true
AUTH_USERNAME=admin
AUTH_PASSWORD_HASH=<compose-safe-bcrypt-hash>
AUTH_SECRET_KEY=<random>
AUTH_TOKEN_EXPIRE_MINUTES=180

PVE_API_URL=https://<proxmox-host>:8006/api2/json
PVE_API_TOKEN_ID=root@pam!pbo-api
PVE_API_TOKEN_SECRET=<secret>
PVE_VERIFY_SSL=false
PVE_NODE_NAME=<node-name>

PBS_API_URL=https://<pbs-vm>:8007/api2/json
PBS_TOKEN_ID=root@pam!pbo-pbs
PBS_TOKEN_SECRET=<secret>
PBS_VERIFY_SSL=false
PBS_DATASTORE=backup-store

PBS_EXECUTION_VM_ID=<pbs-vm-id>
PBS_EXECUTION_VM_NODE=<node-name>

HOST_AGENT_BASE_URL=http://<proxmox-host>:8090
HOST_AGENT_TOKEN=<host-agent-token>
PBS_AGENT_BASE_URL=http://<pbs-vm>:8091
PBS_AGENT_TOKEN=<pbs-agent-token>
```

Generate the admin login hash from the repository root:

```bash
python scripts/generate_password_hash.py
```

Paste the printed `AUTH_PASSWORD_HASH=...` value into `.env`. In Docker Compose `.env` files, every bcrypt `$` must be escaped as `$$`:

```env
AUTH_PASSWORD_HASH=$$2b$$12$$...
```

Generate JWT and agent tokens:

```bash
openssl rand -hex 32  # AUTH_SECRET_KEY
openssl rand -hex 32  # APP_MAINTENANCE_AGENT_TOKEN
openssl rand -hex 32  # HOST_AGENT_TOKEN and Proxmox AGENT_SERVER_TOKEN
openssl rand -hex 32  # PBS_AGENT_TOKEN and PBS AGENT_SERVER_TOKEN
```

Install the local App VM maintenance agent before using Settings > Maintenance:

```bash
cd /opt/proxmox_backup_orchestrator/apps/app-maintenance-agent
python3 -m venv .venv
.venv/bin/pip install -e .
cp deploy/systemd/proxmox-backup-orchestrator-app-maintenance-agent.service \
  /etc/systemd/system/proxmox-backup-orchestrator-app-maintenance-agent.service
systemctl daemon-reload
systemctl enable --now proxmox-backup-orchestrator-app-maintenance-agent.service
systemctl status proxmox-backup-orchestrator-app-maintenance-agent.service
```

Health check on the App VM:

```bash
curl -H "X-Agent-Token: <app-maintenance-agent-token>" http://127.0.0.1:8092/health
```

Start the app stack:

```bash
docker compose -f infra/docker/docker-compose.yml up -d --build
docker compose -f infra/docker/docker-compose.yml ps
```

Login and protected API check:

```bash
TOKEN="$(
  curl -sS -X POST http://127.0.0.1:8000/api/v1/auth/token \
    -H "Content-Type: application/x-www-form-urlencoded" \
    --data-urlencode "username=<admin-username>" \
    --data-urlencode "password=<admin-password>" \
  | jq -r .access_token
)"

curl -H "Authorization: Bearer ${TOKEN}" \
  http://127.0.0.1:8000/api/v1/disks/preferred
```

Expected result: the login request returns an access token, and the preferred disks request returns a JSON array. An empty array is valid before any preferred disk has been saved.

Install `jq` first if it is not available, or copy the `access_token` from the login response manually.

## 3. Install the Proxmox Host Agent

On the Proxmox host:

```bash
mkdir -p /opt/proxmox-backup-orchestrator-agent
rsync -a apps/agent/ /opt/proxmox-backup-orchestrator-agent/
cd /opt/proxmox-backup-orchestrator-agent
python3 -m venv .venv
.venv/bin/pip install -e .
```

Create `/opt/proxmox-backup-orchestrator-agent/.env`:

```env
AGENT_API_BASE_URL=http://<app-vm-ip>:8000/api/v1
AGENT_HOSTNAME=<proxmox-hostname>
AGENT_VERSION=0.1.0
AGENT_TIMEOUT_SECONDS=10
AGENT_INCLUDE_NON_USB_CANDIDATES=false
AGENT_EXPORT_TIMEOUT_SECONDS=7200
AGENT_DATASTORE_CREATE_TIMEOUT_SECONDS=14400
AGENT_SERVER_HOST=0.0.0.0
AGENT_SERVER_PORT=8090
AGENT_SERVER_TOKEN=<same-value-as-HOST_AGENT_TOKEN>
AGENT_REPO_PATH=/opt/proxmox-backup-orchestrator-agent
AGENT_MAINTENANCE_TIMEOUT_SECONDS=120
```

Protect it:

```bash
chown root:root /opt/proxmox-backup-orchestrator-agent/.env
chmod 600 /opt/proxmox-backup-orchestrator-agent/.env
```

Install the systemd service as `proxmox-backup-orchestrator-agent-http.service`. If your repo service file has another name, copy it under this production name:

```bash
cp apps/agent/deploy/systemd/proxmox-backup-orchestrator-agent-api.service \
  /etc/systemd/system/proxmox-backup-orchestrator-agent-http.service
systemctl daemon-reload
systemctl enable --now proxmox-backup-orchestrator-agent-http.service
systemctl status proxmox-backup-orchestrator-agent-http.service
```

Health check from the app VM:

```bash
curl -H "X-Agent-Token: <host-agent-token>" http://<proxmox-host>:8090/health
```

## 4. Install the PBS Agent

On the PBS VM:

```bash
mkdir -p /opt/proxmox-backup-orchestrator-pbs-agent
rsync -a apps/agent/ /opt/proxmox-backup-orchestrator-pbs-agent/
cd /opt/proxmox-backup-orchestrator-pbs-agent
python3 -m venv .venv
.venv/bin/pip install -e .
```

Create `/opt/proxmox-backup-orchestrator-pbs-agent/.env`:

```env
AGENT_API_BASE_URL=http://<app-vm-ip>:8000/api/v1
AGENT_HOSTNAME=<pbs-hostname>
AGENT_VERSION=0.1.0
AGENT_TIMEOUT_SECONDS=10
AGENT_INCLUDE_NON_USB_CANDIDATES=false
AGENT_EXPORT_TIMEOUT_SECONDS=7200
AGENT_DATASTORE_CREATE_TIMEOUT_SECONDS=14400
AGENT_SERVER_HOST=0.0.0.0
AGENT_SERVER_PORT=8091
AGENT_SERVER_TOKEN=<same-value-as-PBS_AGENT_TOKEN>
AGENT_REPO_PATH=/opt/proxmox-backup-orchestrator-pbs-agent
AGENT_MAINTENANCE_TIMEOUT_SECONDS=120
```

Protect it:

```bash
chown root:root /opt/proxmox-backup-orchestrator-pbs-agent/.env
chmod 600 /opt/proxmox-backup-orchestrator-pbs-agent/.env
```

Install the systemd service:

```bash
cp apps/agent/deploy/systemd/proxmox-backup-orchestrator-pbs-agent-api.service \
  /etc/systemd/system/proxmox-backup-orchestrator-pbs-agent-http.service
sed -i 's#/opt/proxmox-backup-orchestrator-agent#/opt/proxmox-backup-orchestrator-pbs-agent#g' \
  /etc/systemd/system/proxmox-backup-orchestrator-pbs-agent-http.service
systemctl daemon-reload
systemctl enable --now proxmox-backup-orchestrator-pbs-agent-http.service
systemctl status proxmox-backup-orchestrator-pbs-agent-http.service
```

Health check from the app VM:

```bash
curl -H "X-Agent-Token: <pbs-agent-token>" http://<pbs-vm>:8091/health
```

## 5. Firewall Rules

Limit agent ports to the app VM IP.

On Proxmox, add a host firewall rule for TCP `8090` from `<app-vm-ip>` only. See [Security](SECURITY.md) for a `host.fw` example.

On PBS, configure `nftables` to allow TCP `8091` from `<app-vm-ip>` only. See [Security](SECURITY.md) for a full example.

## 6. Final Checks

From the app VM:

```bash
TOKEN="$(
  curl -sS -X POST http://127.0.0.1:8000/api/v1/auth/token \
    -H "Content-Type: application/x-www-form-urlencoded" \
    --data-urlencode "username=<admin-username>" \
    --data-urlencode "password=<admin-password>" \
  | jq -r .access_token
)"

curl -H "Authorization: Bearer ${TOKEN}" \
  http://127.0.0.1:8000/api/v1/disks/preferred
curl -H "X-Agent-Token: <host-agent-token>" http://<proxmox-host>:8090/health
curl -H "X-Agent-Token: <pbs-agent-token>" http://<pbs-vm>:8091/health
```

Open the UI:

```text
http://<app-vm-ip>:5173
```

Log in with `AUTH_USERNAME` and the password used to generate `AUTH_PASSWORD_HASH`.

## Troubleshooting

**Login is incorrect due to malformed `AUTH_PASSWORD_HASH`**

If Docker Compose receives an unescaped bcrypt hash, it may interpolate `$2b`, `$12`, or later segments. The API then receives a truncated hash and login fails. Regenerate the hash and paste the Compose-safe value with `$$`.

**`code_secret` still works**

Remove it from every environment file, shell profile, service override, and secret store. This deployment uses `AUTH_PASSWORD_HASH`, `AUTH_SECRET_KEY`, and agent tokens. Restart the app and both agents after cleanup.

**Agent health returns 401**

The `X-Agent-Token` header does not match `AGENT_SERVER_TOKEN` on that agent. Compare `HOST_AGENT_TOKEN` with the Proxmox agent token, and `PBS_AGENT_TOKEN` with the PBS agent token. Restart the affected service after editing `.env`.

**PBS disk is visible but not mounted**

Confirm the disk is attached to the PBS VM, then inspect the PBS agent logs:

```bash
journalctl -u proxmox-backup-orchestrator-pbs-agent-http.service -n 200 --no-pager
```

The first dedicated preparation may need destructive confirmation. Reuse mode should mount the existing PBS datastore without formatting.

**USB passthrough is still attached**

Check the PBS VM config on the Proxmox host:

```bash
qm config <pbs-vm-id> | grep '^usb'
```

Run safe eject again from the UI. If necessary, detach the stale slot manually only after confirming the PBS datastore is unmounted.

**External datastore reuse vs first format**

First preparation of a new dedicated disk can format the disk. Later runs should reuse the existing filesystem and PBS datastore unless force format is explicitly requested.
