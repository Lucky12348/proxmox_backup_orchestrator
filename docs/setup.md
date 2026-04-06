# Setup

## Local Prerequisites

- Python 3.11+
- Node.js 20+
- Docker and Docker Compose

## Initial Setup

1. Copy `.env.example` to `.env`
2. Review and adjust environment variables
3. Run `make bootstrap` to verify the local URLs and environment file
4. Start the local stack with `docker compose -f infra/docker/docker-compose.yml up --build`
5. Open the web dashboard and API docs in the browser
6. Install local app dependencies only if you want to run API or web outside Docker

Use `postgresql+psycopg://...` for `DATABASE_URL`. The backend also rewrites plain
`postgresql://...` URLs to psycopg3 automatically for local compatibility.

The `.env` file must live at the repository root:

- `proxmox_backup_orchestrator/.env`

When you run `docker-compose -f infra/docker/docker-compose.yml up ...` or
`docker compose -f infra/docker/docker-compose.yml up ...`, the API and web
services explicitly load that root `.env` file into their container runtime
environment.

For read-only Proxmox inventory sync, configure these variables in `.env`:

- `PVE_API_URL`
- `PVE_API_TOKEN_ID`
- `PVE_API_TOKEN_SECRET`
- `PVE_VERIFY_SSL`
- `PVE_NODE_NAME`

For read-only PBS backup sync, configure these variables in `.env`:

- `PBS_API_URL`
- `PBS_TOKEN_ID`
- `PBS_TOKEN_SECRET`
- `PBS_VERIFY_SSL`
- `PBS_FINGERPRINT` when the host-side sync remote needs an explicit certificate fingerprint
- `PBS_DATASTORE`

For backend-to-host-agent execution, these variables are also relevant:

- `HOST_AGENT_BASE_URL`
- `HOST_AGENT_TOKEN`
- `HOST_AGENT_TIMEOUT_SECONDS`

For the local host-agent scaffold, these variables are useful when running `apps/agent` manually:

- `AGENT_API_BASE_URL`
- `AGENT_HOSTNAME`
- `AGENT_VERSION`
- `AGENT_TIMEOUT_SECONDS`
- `AGENT_INCLUDE_NON_USB_CANDIDATES`
- `AGENT_STALE_AFTER_MINUTES`
- `AGENT_EXPORT_TIMEOUT_SECONDS`
- `AGENT_SERVER_HOST`
- `AGENT_SERVER_PORT`
- `AGENT_SERVER_TOKEN`

For POSIX shells, a matching helper is available at `infra/scripts/bootstrap.sh`.

## Local URLs

- Web dashboard: `http://localhost:5173`
- API docs: `http://localhost:8000/docs`
- API health: `http://localhost:8000/health`
- API overview: `http://localhost:8000/api/v1/overview`
- Proxmox status: `http://localhost:8000/api/v1/integrations/proxmox/status`
- PBS status: `http://localhost:8000/api/v1/integrations/pbs/status`

## Seed Data

In development, the API creates tables automatically and seeds a small demo dataset on startup if the database is empty.

The seeded data currently includes:

- 4 example workloads: 2 VMs and 2 containers
- 3 example external disks with different connection states
- disk assignment examples
- 2 backup run history entries

The seed routine is idempotent for an empty database and will not duplicate rows on restart.

## Proxmox API Token

The current integration is read-only and syncs inventory from one Proxmox node on demand.

Create an API token in Proxmox VE:

1. Open `Datacenter -> Permissions -> API Tokens`
2. Create a token for a user such as `root@pam`
3. Grant the token read access to VM and container inventory on the target node
4. Copy the token identifier into `PVE_API_TOKEN_ID`
5. Copy the generated secret into `PVE_API_TOKEN_SECRET`

For a local self-signed Proxmox setup, keep `PVE_VERIFY_SSL=false`. For a trusted certificate, set it to `true`.

After the stack starts, use the dashboard's Proxmox section to test the connection status and trigger a manual inventory sync.

## PBS Credentials

The PBS integration is also read-only at this stage. It fetches snapshots from one configured datastore and updates `last_backup_at` for matching Proxmox inventory rows.

Configure:

1. `PBS_API_URL` with your PBS API base URL ending in `/api2/json`
2. `PBS_TOKEN_ID` with a PBS API token id such as `root@pam!pbo-pbs`
3. `PBS_TOKEN_SECRET` with the generated token secret
4. `PBS_DATASTORE` with the datastore name to inspect
5. `PBS_VERIFY_SSL=false` for self-signed local setups, or `true` for trusted certificates

After the stack starts, use the dashboard's PBS section to check connectivity and trigger a manual backup sync.

## Host Agent Scaffold

The host agent is still intentionally simple in this phase. It does not watch hotplug events yet, but it now runs as a small HTTP daemon for on-demand actions alongside the existing timer-driven sync job.
The host-side deployment now has a daemon for HTTP actions and a timer for state sync.

It currently supports:

- sending a heartbeat to the backend
- sending a real disk report based on Linux host inspection
- sending a combined heartbeat + real disk report with `sync-state`
- serving authenticated HTTP endpoints for `GET /health`, `POST /prepare-disk`, `POST /prepare-external-datastore`, and `POST /run-external-export`
- preparing a dedicated target directory for an external PBS export flow
- running a real PBS-native-like external export boundary when `proxmox-backup-manager` is available
- sending a mock external-disk report for fallback testing

Example local commands:

```bash
cd apps/agent
python -m venv .venv
source .venv/bin/activate
pip install -e .
python -m agent.main heartbeat
python -m agent.main report-disks
python -m agent.main sync-state
uvicorn agent.server:app --host 0.0.0.0 --port 8081
python -m agent.main prepare-external-datastore --mount-path /mnt/backup --target-path /mnt/backup/pbs-datastore --mode dedicated
python -m agent.main run-external-export --target-path /mnt/backup/pbs-datastore --datastore-name backup --mode dedicated
python -m agent.main report-mock-disks
```

Run the agent on the Proxmox host itself so `lsblk -J` reflects the real attached storage.

The current real disk report now defaults to strict external-only detection:

- only `TYPE=disk`
- excludes `loop`, `dm-*`, `zd*`, and `sr*`
- excludes disks backing `/` or `/boot/efi`
- excludes obvious system storage members such as `LVM2_member` and `zfs_member`
- reports only disks that are clearly external or removable
- examples include `TRAN=usb`, `RM=1`, `HOTPLUG=1`, `ID_BUS=usb`, or USB-related udev properties
- internal SATA or ATA disks are excluded by default, even if they look unused

If you explicitly want the older advanced behavior, set:

- `AGENT_INCLUDE_NON_USB_CANDIDATES=true`

That advanced mode may include standalone non-system physical disks again, but the safe default is `false`.

Once a real disk report has been sent, the dashboard prefers agent-reported disks over seeded demo disks.
When a new report arrives from the same host, previously agent-reported disks that are no longer present are marked inactive and disappear from the preferred disk view.

This matters because valid backup disks on a Proxmox host may appear as SATA/ATA disks rather than USB devices.
The dashboard now distinguishes:

- candidate disks detected by the agent
- trusted disks explicitly approved in the UI

Trusted disks are the only disks that participate in backup planning.
Planning in this MVP is intentionally simple:

- use `size_gb` for each enabled VM or CT
- use either `usable_capacity_gb` or the full disk capacity
- subtract `reserved_capacity_gb`
- ignore real PBS dedup/chunk behavior for now

The first external PBS export MVP builds on that disk model:

- if a disk is marked as dedicated, the app uses a clean `pbs-datastore` target directory
- if a disk allows existing data, the app writes into an isolated application subdirectory:
  `proxmox-backup-orchestrator/<serial>/pbs-datastore`
- coexistence mode never writes directly to the disk root
- this phase replaces the earlier stub with a real host-side PBS-native-like sync attempt
- the backend now calls the host agent over HTTP instead of trying to start host binaries locally
- the agent prepares the target directory, then uses `proxmox-backup-manager` to create a local datastore, a temporary remote, and a temporary sync job before running the sync
- full restore workflow comes later

Host-side dependencies for that execution path:

- `proxmox-backup-manager` must be installed on the machine running the agent command
- the agent HTTP service must run on the Proxmox/PBS-capable host so host-local commands can access host storage and PBS tooling
- the backend must be able to reach `HOST_AGENT_BASE_URL`
- the backend and host agent must share the same token through `HOST_AGENT_TOKEN` and `AGENT_SERVER_TOKEN`
- the host agent environment must include valid `PBS_API_URL`, `PBS_TOKEN_ID`, `PBS_TOKEN_SECRET`, and usually `PBS_DATASTORE`
- if the PBS certificate is not already trusted by the host, `PBS_FINGERPRINT` may also be required

When an external backup run finishes, the API stores:

- final status and message
- exact command
- execution cwd
- return code
- captured stdout log
- captured stderr log

Those details are visible from the Activity page and the `/api/v1/external-backups/runs` and `/api/v1/external-backups/runs/{id}` APIs.

When a run fails, inspect logs in this order:

- the Activity page detail section for the persisted message, command summary, return code, stdout, and stderr excerpts
- the Activity page detail section for the persisted message, command summary, cwd, return code, stdout, and stderr excerpts
- `GET /api/v1/external-backups/runs/{id}` for the stored run payload
- `journalctl -u proxmox-backup-orchestrator-agent-api.service` on the host running the agent API

Disk preparation can now be triggered directly from the app through the host agent:

- preserve-existing-data mode mounts the existing filesystem under an application-managed path such as `/mnt/pbo/<serial>`
- dedicated mode formats the selected disk as `ext4`, mounts it under an application-managed path, and is destructive
- the goal is to remove manual shell preparation before later external PBS exports

The backend considers the agent:

- `connected` when the last heartbeat is newer than `AGENT_STALE_AFTER_MINUTES`
- `degraded` when a heartbeat exists but is older than that threshold
- `disconnected` when no heartbeat has been recorded yet

If PBS returns `401 Unauthorized`, verify:

- the token id and secret are correct
- the token has ACLs allowing API access
- the token can read the configured datastore

## Example Commands

### API

```bash
cd apps/api
python -m venv .venv
source .venv/bin/activate
pip install -e .
uvicorn app.main:app --reload
```

### Web

```bash
cd apps/web
npm install
npm run dev
```

### Agent

```bash
cd apps/agent
python -m venv .venv
source .venv/bin/activate
pip install -e .
python -m agent.main
```

## Proxmox Host Agent Deployment

To run the agent persistently on the Proxmox host:

1. Copy `apps/agent` to a host path such as `/opt/proxmox-backup-orchestrator-agent`
2. Create a virtual environment there
3. Install the package into that venv
4. Create `/opt/proxmox-backup-orchestrator-agent/.env` with:
   - `AGENT_API_BASE_URL`
   - `AGENT_HOSTNAME`
   - `AGENT_VERSION`
   - `AGENT_TIMEOUT_SECONDS`
   - `AGENT_SERVER_TOKEN`
   - `AGENT_SERVER_PORT` if you do not want `8081`
5. Copy:
   - `apps/agent/deploy/systemd/proxmox-backup-orchestrator-agent-api.service`
   - `apps/agent/deploy/systemd/proxmox-backup-orchestrator-agent.service`
   - `apps/agent/deploy/systemd/proxmox-backup-orchestrator-agent.timer`
   into `/etc/systemd/system/`
6. Run:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now proxmox-backup-orchestrator-agent-api.service
sudo systemctl enable --now proxmox-backup-orchestrator-agent.timer
```

The split is intentional:

- `proxmox-backup-orchestrator-agent-api.service` exposes the host-local action API
- `proxmox-backup-orchestrator-agent.timer` continues to schedule heartbeat and disk report syncs
- the backend talks to the host agent with `HOST_AGENT_BASE_URL`, `HOST_AGENT_TOKEN`, and `HOST_AGENT_TIMEOUT_SECONDS`

For debugging on the Proxmox host:

```bash
cd /opt/proxmox-backup-orchestrator-agent
source .venv/bin/activate
python -m agent.main sync-state
uvicorn agent.server:app --host 0.0.0.0 --port 8081
python -m agent.main prepare-external-datastore --mount-path /mnt/backup --target-path /mnt/backup/pbs-datastore --mode dedicated
python -m agent.main run-external-export --target-path /mnt/backup/pbs-datastore --datastore-name backup --mode dedicated
```

To inspect logs:

```bash
sudo journalctl -u proxmox-backup-orchestrator-agent-api.service -f
sudo journalctl -u proxmox-backup-orchestrator-agent.service -f
sudo systemctl list-timers proxmox-backup-orchestrator-agent.timer
```

### Docker

```bash
cp .env.example .env
make bootstrap
docker compose -f infra/docker/docker-compose.yml up --build
```

Once the stack is running, open `http://localhost:5173`.
