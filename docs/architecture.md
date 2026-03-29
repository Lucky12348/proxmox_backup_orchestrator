# Architecture

## High-Level Design

The current MVP stage is intentionally simple:

- a dedicated VM runs the API, web application, and PostgreSQL database
- a lightweight Python agent runs directly on a Proxmox host
- Proxmox Backup Server (PBS) remains the backup engine
- external removable disks are attached to the Proxmox host and observed by the agent
- notifications are emitted through `ntfy`

## Component Roles

### VM for App

The application VM hosts the main control plane:

- FastAPI backend with PostgreSQL-backed domain models and REST endpoints
- React frontend for monitoring and simple operator edits
- read-only Proxmox VE inventory sync for one configured node
- read-only PBS snapshot sync for one configured datastore
- PostgreSQL for persisted application state

## Current Domain Scope

This stage introduces database-backed MVP entities for:

- virtual machines and containers
- external removable disks
- disk-to-workload assignments
- backup run history

The dashboard currently reads from the API, can trigger a read-only Proxmox inventory sync, and exposes a small amount of inline editing for MVP flags.

## Proxmox Integration

The first infrastructure integration is intentionally narrow:

- the backend checks connectivity to the Proxmox VE API
- it fetches QEMU VM and LXC container inventory from one configured node
- it upserts that inventory into the existing `VirtualMachine` table
- it preserves user-managed metadata such as the `critical` flag

This integration is read-only. It does not create, modify, or delete workloads in Proxmox VE.

## PBS Integration

The PBS integration is also intentionally narrow:

- the backend checks connectivity to the PBS API
- it reads snapshot metadata from one configured datastore
- it infers the most recent backup time per VM or CT
- it updates `VirtualMachine.last_backup_at` for matching Proxmox inventory rows

Authentication is done with a PBS API token, not user-password basic auth. Token ACLs and datastore permissions are managed on PBS.

This phase is read-only. It does not orchestrate disks, trigger exports, or manage retention.

### Agent on Proxmox Host

The agent is expected to run close to the hardware and later provide:

- USB disk detection
- mount / presence reporting
- host-local signals useful for removable-media workflows

### PBS as Backup Engine

PBS remains responsible for performing and storing backups. The orchestrator focuses on coordination, visibility, and workflow state rather than replacing PBS.

Disk orchestration, removable-media exports, and USB agent coordination are still deferred. This phase only establishes read-only inventory and backup visibility.

### External Removable Disks

External disks are part of the operational model for offline or rotating backup media. The future system should track whether required disks are present before specific backup actions are triggered.

### Notifications via ntfy

`ntfy` is intended for simple event notifications such as:

- disk missing
- backup completed
- backup failed
- operator action required
