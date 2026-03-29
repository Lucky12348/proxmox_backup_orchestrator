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
- `PBS_DATASTORE`

For the local host-agent scaffold, these variables are useful when running `apps/agent` manually:

- `AGENT_API_BASE_URL`
- `AGENT_HOSTNAME`
- `AGENT_VERSION`
- `AGENT_TIMEOUT_SECONDS`

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

The host agent is still intentionally simple in this phase. It does not run as a daemon and does not watch hotplug events yet.

It currently supports:

- sending a heartbeat to the backend
- sending a real disk report based on Linux host inspection
- sending a mock external-disk report for fallback testing

Example local commands:

```bash
cd apps/agent
python -m venv .venv
source .venv/bin/activate
pip install -e .
python -m agent.main heartbeat
python -m agent.main report-disks
python -m agent.main report-mock-disks
```

Run the agent on the Proxmox host itself so `lsblk -J` reflects the real attached storage.

The current real disk report uses pragmatic backup-candidate heuristics:

- only `TYPE=disk`
- excludes `loop`, `dm-*`, `zd*`, and `sr*`
- excludes disks backing `/` or `/boot/efi`
- excludes obvious system storage members such as `LVM2_member` and `zfs_member`
- still allows clearly external USB disks
- also allows standalone SATA/ATA disks when they are not obviously part of the Proxmox system or storage stack

Once a real disk report has been sent, the dashboard prefers agent-reported disks over seeded demo disks.

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

### Docker

```bash
cp .env.example .env
make bootstrap
docker compose -f infra/docker/docker-compose.yml up --build
```

Once the stack is running, open `http://localhost:5173`.
