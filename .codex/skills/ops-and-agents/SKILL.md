---
name: ops-and-agents
description: Work on Proxmox/PBS agents, Docker Compose deployment, systemd services, maintenance flows, and operational troubleshooting in proxmox_backup_orchestrator. Use when touching host agents, PBS execution behavior, maintenance agents, environment wiring, deployment files, or production-facing operational docs.
---

# Ops And Agents

Read these files first for operational tasks:

- `README.md`
- `docs/INSTALLATION.md`
- `docs/OPERATIONS.md`
- `docs/MAINTENANCE.md`
- `docs/SECURITY.md`
- `infra/docker/docker-compose.yml`

Know the component boundaries:

- `apps/agent` is deployed in two roles: Proxmox host agent and PBS agent.
- `apps/app-maintenance-agent` is local to the app VM and manages git/compose update flows.
- `apps/api` orchestrates those agents through authenticated HTTP calls.

Use these code entrypoints:

- `apps/agent/src/agent/main.py`
- `apps/agent/src/agent/server.py`
- `apps/app-maintenance-agent/src/app_maintenance_agent/main.py`
- `apps/api/app/services/host_agent.py`
- `apps/api/app/services/external_backup_agent.py`
- `apps/api/app/services/maintenance.py`

Respect these operational rules:

- Treat agent ports `8090`, `8091`, and `8092` as restricted surfaces.
- Preserve `X-Agent-Token` authentication on all privileged HTTP actions.
- Assume disk preparation, partitioning, mounting, USB passthrough, and PBS datastore work are safety-critical.
- Confirm whether a change affects the Proxmox host agent, PBS agent, app maintenance agent, or all three.

Read deployment wiring before editing:

- Read `infra/docker/docker-compose.yml` for the app VM stack.
- Read `apps/agent/deploy/systemd/` for host and PBS agent service/timer deployment.
- Read `apps/app-maintenance-agent/deploy/systemd/` for app VM maintenance deployment.
- Read `.env.example` for the expected variable contract across app VM and agents.

Use cautious review rules for destructive paths:

- Inspect code paths that call mount, format, wipe, `qm`, `parted`, `wipefs`, `sgdisk`, or `proxmox-backup-manager`.
- Do not relax device filtering or destructive confirmations without checking the operational docs and tests.
- Keep maintenance behavior explicit about git state, `.env` preservation, and restart side effects.

Use these tests when relevant:

- `apps/api/tests/test_proxmox_client.py`
- `apps/api/tests/test_external_backup_execution.py`
- `apps/api/tests/test_disk_handoff.py`
- `apps/app-maintenance-agent/tests/test_env_preservation.py`
- `apps/agent/tests/test_external_export.py`

For troubleshooting work:

- Start from the failing surface: app VM, Proxmox host agent, PBS agent, or maintenance agent.
- Trace the exact HTTP boundary and token/env dependency before proposing a fix.
- Update the matching docs when changing deployment assumptions, ports, service names, or required environment variables.
