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

## Quick Start

1. Copy `.env.example` to `.env` and adjust values, or run `make bootstrap`.
2. Start local services with `make up`.
3. Run development commands from each app directory as needed.

See [docs/setup.md](docs/setup.md) for details.
