# Architecture

## High-Level Design

The initial target architecture is intentionally simple:

- a dedicated VM runs the API, web application, and PostgreSQL database
- a lightweight Python agent runs directly on a Proxmox host
- Proxmox Backup Server (PBS) remains the backup engine
- external removable disks are attached to the Proxmox host and observed by the agent
- notifications are emitted through `ntfy`

## Component Roles

### VM for App

The application VM hosts the main control plane:

- FastAPI backend for orchestration and persistence
- React frontend for monitoring and operator actions
- PostgreSQL for application state

### Agent on Proxmox Host

The agent is expected to run close to the hardware and later provide:

- USB disk detection
- mount / presence reporting
- host-local signals useful for removable-media workflows

### PBS as Backup Engine

PBS remains responsible for performing and storing backups. The orchestrator will focus on coordination, visibility, and workflow state rather than replacing PBS.

### External Removable Disks

External disks are part of the operational model for offline or rotating backup media. The future system should track whether required disks are present before specific backup actions are triggered.

### Notifications via ntfy

`ntfy` is intended for simple event notifications such as:

- disk missing
- backup completed
- backup failed
- operator action required
