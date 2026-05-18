# proxmox_backup_orchestrator

Production-oriented monorepo scaffold for a personal Proxmox / Proxmox Backup Server backup orchestration application.

## Structure

```text
proxmox_backup_orchestrator/
|- apps/
|  |- agent/    # Host-side Python agent placeholder
|  |- api/      # FastAPI backend
|  `- web/      # React + Vite frontend
|- docs/        # Architecture and setup documentation
|- infra/
|  |- docker/   # Docker Compose and container files
|  `- scripts/  # Helper scripts
`- packages/
   |- types/    # Shared schemas / contracts
   `- utils/    # Shared utilities
```

## Purpose

This repository is intended to orchestrate backups around a small Proxmox environment:

- a backend API to coordinate state and workflows
- a frontend dashboard to monitor coverage and removable media
- a lightweight agent running on a Proxmox host
- PostgreSQL for application state
- Proxmox Backup Server as the backup engine
- `ntfy` for notifications

## External Backup Workflow

The recommended external backup workflow uses a dedicated PBS datastore disk:

1. The Proxmox host agent detects a trusted USB disk.
2. The API hands the USB device to the PBS VM.
3. The PBS agent destructively formats the disk as ext4.
4. The disk is mounted at `/mnt/pbo/<serial>/pbs-datastore`.
5. PBS sync copies backups from the configured source datastore, usually `backup-store`, into the dedicated disk datastore.

This path is intentionally destructive: existing data on the selected disk is removed. The old coexistence loop-backed mode remains as an advanced legacy path behind `EXTERNAL_BACKUP_LEGACY_COEXISTENCE_ENABLED=true`.

Restore concept: reinstall PBS if needed, attach the disk, mount `/mnt/pbo/<serial>/pbs-datastore`, then add that path back as a PBS datastore.

## Quick Start

1. Copy `.env.example` to `.env` and adjust values, or run `make bootstrap`.
2. Start local services with `make up`.
3. Run development commands from each app directory as needed.

See [docs/setup.md](docs/setup.md) for details.

## Authentication

The API uses a single local admin account when `AUTH_ENABLED=true`.

```env
AUTH_ENABLED=true
AUTH_USERNAME=admin
AUTH_PASSWORD_HASH=$2b$12$replace-with-generated-bcrypt-hash
AUTH_SECRET_KEY=replace-with-random-secret
AUTH_TOKEN_EXPIRE_MINUTES=480
```

Generate the password hash from the repository root:

```powershell
py scripts/generate_password_hash.py
```

The script prints `AUTH_PASSWORD_HASH=<hash>` for `.env`. Bcrypt only accepts passwords up to 72 bytes after UTF-8 encoding, so long passphrases with non-ASCII characters can hit the limit sooner than expected.
