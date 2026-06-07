---
name: backup-workflow-backend
description: Work safely on the FastAPI backend and backup orchestration flows in proxmox_backup_orchestrator. Use when changing API routes, backend services, models, schemas, planning, notifications, disk handling, USB handoff, or PBS external backup execution.
---

# Backup Workflow Backend

Read these files first:

- `apps/api/app/main.py`
- `apps/api/app/api/router.py`
- `apps/api/app/core/config.py`
- `apps/api/app/services/`
- `apps/api/app/api/routes/`

Understand the backend shape before editing:

- Routes in `apps/api/app/api/routes/` expose the HTTP surface.
- Services in `apps/api/app/services/` hold most orchestration logic.
- Models in `apps/api/app/models/` define persisted state.
- Schemas in `apps/api/app/schemas/` define request and response contracts.
- The app starts tables and non-production seeding from `apps/api/app/main.py`.

Follow the main execution chain for external backup work:

1. Start at `apps/api/app/api/routes/external_backups.py`, `disks.py`, `agent.py`, or `maintenance.py`.
2. Trace into `apps/api/app/services/external_backup_execution.py`, `external_backups.py`, `disk_handoff.py`, `disk_preparation_agent.py`, `host_agent.py`, and `external_backup_agent.py`.
3. Verify which calls go to the Proxmox host agent and which go to the PBS agent.
4. Confirm the persisted side effects in the relevant models before changing behavior.

Treat these areas as sensitive:

- `external_backup*`: removable-media orchestration, progress callbacks, cleanup, run status.
- `disk_*`, `disks.py`, `disk_handoff.py`, `disk_preparation_agent.py`: destructive or hardware-adjacent workflows.
- `planning*`: scheduler behavior, reminders, planning assumptions.
- `notifications*`: production alerting and env-gated delivery behavior.
- `proxmox_*` and `pbs_*`: external system integration and sync state.

Verify environment assumptions before changing behavior:

- Read `apps/api/app/core/config.py`.
- Cross-check `.env.example` for variable names, defaults, and deployment expectations.
- Cross-check `infra/docker/docker-compose.yml` for what is actually injected in the app VM stack.

Prefer these tests when touching backend orchestration:

- `apps/api/tests/test_external_backup_execution.py`
- `apps/api/tests/test_external_backup_conflicts_progress.py`
- `apps/api/tests/test_disk_handoff.py`
- `apps/api/tests/test_disks.py`
- `apps/api/tests/test_notifications.py`
- `apps/api/tests/test_notification_preferences.py`
- `apps/api/tests/test_planning_events.py`
- `apps/api/tests/test_pbs_coverage.py`

When changing API behavior:

- Update the route, service, schema, and tests together.
- Preserve auth boundaries in `apps/api/app/api/router.py`.
- Keep public callback routes and protected operator routes distinct.

When changing privileged workflows:

- Read `docs/OPERATIONS.md`, `docs/INSTALLATION.md`, and `docs/SECURITY.md` first.
- Do not weaken token checks, callback trust, or network-scope assumptions without updating the docs and deployment story.
