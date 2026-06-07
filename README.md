<p align="center">
  <img src="docs/assets/beautyfullImage.png" alt="Proxmox Backup Orchestrator presentation logo" width="720">
</p>

# Proxmox Backup Orchestrator

Proxmox Backup Orchestrator is a specialized control plane for rotating external-disk backups in a small Proxmox VE and Proxmox Backup Server environment. It keeps the web UI and API inside an application VM while privileged disk, passthrough, and PBS datastore actions stay behind dedicated root agents on the Proxmox host and the PBS VM.

## What It Does

The project coordinates a focused removable-media workflow:

1. Detect an eligible external disk on the Proxmox host.
2. Pass that USB device through to the PBS VM.
3. Prepare or reuse a PBS datastore on the external media.
4. Sync backups from the main PBS datastore to the removable datastore.
5. Safely eject the disk by unmounting it on PBS and removing USB passthrough.

The same control plane also covers inventory sync, backup visibility, planning, notifications, and maintenance operations around that workflow.

## Architecture

```text
Browser
  |
  v
App VM: proxmox_backup_orchestrator
  Docker Compose
    - apps/web  -> React + Vite UI
    - apps/api  -> FastAPI control plane
    - Postgres  -> persisted state
  Local helper
    - apps/app-maintenance-agent -> repo update / compose maintenance API
  |
  | HTTP + shared tokens
  v
Proxmox host root agent
  - disk discovery
  - disk preparation helpers
  - QEMU USB passthrough attach/detach
  - maintenance endpoints for the host-side agent checkout
  |
  | USB passthrough
  v
PBS VM root agent
  - inspect visible disks
  - prepare dedicated PBS datastore
  - run PBS-native sync/export operations
  - safe eject / cleanup helpers
```

Operationally important defaults:

- App VM API: `8000`
- App VM web UI: `5173`
- App maintenance agent: `8092`
- Proxmox host agent: `8090`
- PBS agent: `8091`

Agent ports are intended to be tightly firewalled. The app VM should be the only machine allowed to reach them, and every call is additionally protected with `X-Agent-Token`.

## Repository Map

- `apps/api`: FastAPI backend, database models, schemas, routes, orchestration services, auth.
- `apps/web`: React + Vite frontend for dashboards, disks, planning, integrations, maintenance, and activity views.
- `apps/agent`: root-capable Python agent used on both the Proxmox host and PBS VM.
- `apps/app-maintenance-agent`: local maintenance API for checking git state and rebuilding the app stack on the app VM.
- `infra/docker`: Dockerfiles and the main `docker-compose.yml` used by the app VM.
- `infra/scripts`: bootstrap helpers for local setup.
- `docs`: production-oriented runbooks and architecture/operations documentation.
- `scripts`: small local utilities such as admin password hash generation.
- `packages`: reserved shared package area; currently lightweight compared with the app directories.

## Main Workflows

### External backup workflow

1. The API receives an operator action from the web UI.
2. The API coordinates the Proxmox host agent to inspect the selected disk and manage USB passthrough.
3. The API coordinates the PBS agent to prepare or reuse the target datastore.
4. The PBS agent runs the export/sync boundary and reports progress back to the API.
5. The UI reads persisted activity and run state from Postgres.

### Safe eject workflow

1. The API asks the PBS agent to unmount and clean up the dedicated datastore.
2. The API asks the Proxmox host agent to detach the USB device from the PBS VM.
3. The UI exposes the disk as safe to unplug.

### Maintenance workflow

1. The API or UI checks the local app maintenance agent for repository status.
2. The maintenance agent validates `.env`, checks git state, and can rebuild the Docker Compose stack.
3. The host-side agent codebase has a similar maintenance surface for its own checkout.

## Local Development

The repository is structured as a monorepo, but app setup is still mostly per-application.

### API

```powershell
cd apps/api
py -m venv .venv
.venv\Scripts\pip install -e .
.venv\Scripts\uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Web

```powershell
cd apps/web
npm install
npm run dev
```

### App stack with Docker Compose

```powershell
Copy-Item .env.example .env
docker compose -f infra/docker/docker-compose.yml up --build
```

### Generate the admin password hash

```powershell
py scripts/generate_password_hash.py
```

The script prints a Compose-safe `AUTH_PASSWORD_HASH=...` line. Keep the doubled `$` characters intact when copying into `.env`.

## Production And Operations Docs

- [Installation](docs/INSTALLATION.md)
- [Operations](docs/OPERATIONS.md)
- [Maintenance](docs/MAINTENANCE.md)
- [Security](docs/SECURITY.md)
- [Disaster Recovery](docs/DISASTER_RECOVERY.md)
- [Protection Management](docs/PROTECTION.md)
- [Restore](docs/RESTORE.md)
- [Notifications](docs/NOTIFICATIONS.md)
- [Planning](docs/PLANNING.md)
- [Architecture Notes](docs/architecture.md)

## Safety Notes

- Dedicated PBS datastore preparation can format the selected disk. Treat it as destructive until proven otherwise.
- Do not expose ports `8090`, `8091`, or `8092` broadly. Restrict them to the app VM or localhost as appropriate.
- Never commit `.env` or agent environment files. Shared tokens and API secrets are the trust boundary for privileged actions.
- Bcrypt hashes in Docker Compose env files must escape `$` as `$$`, or the API may receive a truncated hash and reject login.
- The agents execute host-local commands such as mount, partition, QEMU USB attach/detach, and `proxmox-backup-manager`. Read the relevant docs before changing those paths.

## Current Constraints

- The product is intentionally single-user and admin-driven.
- The backup flow is specialized for removable-media PBS replication, not a generic backup orchestrator.
- Real privileged operations depend on the host and PBS agents running with root-level capabilities.
- PBS-native export behavior depends on `proxmox-backup-manager` and real PBS host semantics.
- Some monorepo convenience targets in `Makefile` are placeholders; the most reliable commands remain the per-app ones and Docker Compose.

## Agent Onboarding

Repo-local Codex skills live under `.codex/skills` and are intended to speed up future work:

- `project-orientation`
- `backup-workflow-backend`
- `ops-and-agents`

Use them as navigation and safety guides, then defer to the docs and source of truth in the repository.
