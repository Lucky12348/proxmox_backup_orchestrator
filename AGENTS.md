# AGENTS.md — AI Agent Guide for Proxmox Backup Orchestrator

This file is the single, tool-agnostic entry point for any AI coding agent working
in this repository (Claude Code, OpenAI Codex, Cursor, GitHub Copilot, or any other
agent that reads `AGENTS.md`). Read it before making changes.

Repo-local Codex skills also exist under `.codex/skills/` with the same content
broken into task-specific slices (`project-orientation`, `backup-workflow-backend`,
`ops-and-agents`). They remain valid for tools that support Codex-style skills, but
this file is the canonical source — keep both in sync if you edit one.

## Hard rule: no autonomous git commit/push

**Never run `git commit`, `git push`, or otherwise publish changes on your own
initiative.** Make the requested code changes, leave them uncommitted in the
working tree, and tell the user what changed and why. Only commit or push if the
user explicitly asks for it in that turn. This applies to every agent and every
session, with no exceptions for "small" or "safe" changes.

## What the project does

Proxmox Backup Orchestrator is a specialized control plane for rotating
external-disk backups in a small Proxmox VE + Proxmox Backup Server (PBS)
environment. The web UI and API live in an application VM; privileged disk,
USB-passthrough, and PBS datastore actions stay behind dedicated root agents on
the Proxmox host and the PBS VM.

Core workflow:

1. Detect an eligible external disk on the Proxmox host.
2. Pass that USB device through to the PBS VM.
3. Prepare or reuse a PBS datastore on the external media.
4. Sync backups from the main PBS datastore to the removable datastore.
5. Safely eject the disk (unmount on PBS + remove USB passthrough).

The same control plane also covers inventory sync, backup visibility, planning
(scheduling), notifications, and maintenance operations around that workflow.

Current constraints (do not silently "fix" these — they are intentional unless a
task asks you to change them):

- Single-user, admin-driven product. Auth is one hardcoded account
  (`AUTH_USERNAME` / `AUTH_PASSWORD_HASH` in env, see `apps/api/app/auth.py`), no
  `users` table, no roles/permissions.
- The backup flow is specialized for removable-media PBS replication, not a
  generic backup orchestrator.
- Real privileged operations depend on the host and PBS agents running with
  root-level capabilities.
- PBS-native export behavior depends on `proxmox-backup-manager` and real PBS
  host semantics.
- `Makefile` targets `install`, `dev`, `lint`, `test` are placeholders (`@echo`).
  Use the per-app commands below or Docker Compose instead.

See `ROADMAP.md` for planned/known-missing work (CI, e2e tests, multi-user,
auto-eject gaps, etc.) before assuming something is unimplemented by accident.

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

Default ports: App VM API `8000`, web UI `5173`, app maintenance agent `8092`,
Proxmox host agent `8090`, PBS agent `8091`. Agent ports are meant to be tightly
firewalled — only the app VM should reach them — and every call is additionally
protected with an `X-Agent-Token` header.

## Repository map

- `apps/api` — FastAPI backend: routes, services, models, schemas, auth.
- `apps/web` — React + Vite frontend: dashboards, disks, planning, integrations,
  maintenance, activity views.
- `apps/agent` — root-capable Python agent, deployed on both the Proxmox host
  and the PBS VM.
- `apps/app-maintenance-agent` — local maintenance API for checking git state
  and rebuilding the app stack on the app VM.
- `infra/docker` — Dockerfiles and `docker-compose.yml` for the app VM.
- `infra/scripts` — bootstrap helpers for local setup.
- `docs` — production-oriented runbooks and architecture/operations docs.
- `scripts` — small local utilities (e.g. admin password hash generation).
- `packages/types`, `packages/utils` — reserved, currently empty placeholders
  (README + `.gitkeep` only). Do not assume shared code lives there yet.

## Entrypoints

- API: `apps/api/app/main.py`, router in `apps/api/app/api/router.py`.
- Web: `apps/web/src/App.tsx`.
- Host/PBS agent: `apps/agent/src/agent/main.py` (core logic, ~3000 lines) and
  `apps/agent/src/agent/server.py` (HTTP exposure).
- App maintenance agent: `apps/app-maintenance-agent/src/app_maintenance_agent/main.py`.

## Route yourself by task

- Endpoints, auth, UI data, API regressions → `apps/api/app/api/routes/`.
- Business rules, orchestration, planning, sync, notifications, disk handling,
  external backups → `apps/api/app/services/`.
- Persistence or response-shape changes → `apps/api/app/models/` and
  `apps/api/app/schemas/`.
- Screen-oriented work → `apps/web/src/pages/`.
- Frontend behavior/data fetching → `apps/web/src/components/` and
  `apps/web/src/api.ts`.
- Disk discovery, USB passthrough, datastore preparation, export execution, safe
  eject → `apps/agent/`.
- Before touching deployment or privileged flows → read `docs/INSTALLATION.md`,
  `docs/OPERATIONS.md`, `docs/SECURITY.md` first.

Prefer targeted search (`rg "symbol-or-endpoint"`) over reading the whole repo.
Treat source of truth as layered: runtime code first, then `README.md`, then
`docs/*.md`.

## Backend deep-dive (FastAPI orchestration)

Read `apps/api/app/main.py`, `apps/api/app/api/router.py`,
`apps/api/app/core/config.py`, `apps/api/app/services/`, and
`apps/api/app/api/routes/` before editing backend behavior.

- Routes expose the HTTP surface (`apps/api/app/api/routes/`).
- Services hold most orchestration logic (`apps/api/app/services/`).
- Models define persisted state (`apps/api/app/models/`).
- Schemas define request/response contracts (`apps/api/app/schemas/`).

External backup execution chain: start at
`apps/api/app/api/routes/external_backups.py`, `disks.py`, `agent.py`, or
`maintenance.py`, then trace into
`apps/api/app/services/external_backup_execution.py`,
`external_backups.py`, `disk_handoff.py`, `disk_preparation_agent.py`,
`host_agent.py`, and `external_backup_agent.py`. Verify which calls go to the
Proxmox host agent and which go to the PBS agent, and confirm persisted side
effects in the relevant models before changing behavior.

Sensitive areas — read the code and tests carefully before touching:

- `external_backup*` — removable-media orchestration, progress callbacks,
  cleanup, run status.
- `disk_*`, `disks.py`, `disk_handoff.py`, `disk_eject.py`,
  `disk_preparation_agent.py` — destructive or hardware-adjacent workflows.
  Note: eject today only supports disks that are `dedicated_backup_disk` or
  `prepared_as_pbs_datastore` (see `disk_eject.py`); there is currently no eject
  path for coexistence-mode disks — see `ROADMAP.md`.
- `planning*` — scheduler behavior, reminders, planning assumptions. Auto-eject
  after a successful run is currently wired only through
  `ScheduledBackupEvent.auto_eject_after_success` in `planning_scheduler.py`,
  not for manual/on-demand runs (`external_backups.py`).
- `notifications*` — production alerting and env-gated delivery behavior.
- `proxmox_*` and `pbs_*` — external system integration and sync state.

Before changing behavior, cross-check `apps/api/app/core/config.py`,
`.env.example`, and `infra/docker/docker-compose.yml` for what is actually
injected in the app VM stack.

Relevant tests to run when touching backend orchestration:
`apps/api/tests/test_external_backup_execution.py`,
`test_external_backup_conflicts_progress.py`, `test_disk_handoff.py`,
`test_disks.py`, `test_notifications.py`, `test_notification_preferences.py`,
`test_planning_events.py`, `test_pbs_coverage.py`.

When changing API behavior: update route, service, schema, and tests together.
Preserve auth boundaries in `apps/api/app/api/router.py`, and keep public
callback routes and protected operator routes distinct.

## Ops, agents, and deployment

Read `README.md`, `docs/INSTALLATION.md`, `docs/OPERATIONS.md`,
`docs/MAINTENANCE.md`, `docs/SECURITY.md`, and
`infra/docker/docker-compose.yml` before operational work.

Component boundaries:

- `apps/agent` is deployed in two roles: Proxmox host agent and PBS agent.
- `apps/app-maintenance-agent` is local to the app VM and manages git/compose
  update flows.
- `apps/api` orchestrates those agents through authenticated HTTP calls.

Code entrypoints: `apps/agent/src/agent/main.py`, `apps/agent/src/agent/server.py`,
`apps/app-maintenance-agent/src/app_maintenance_agent/main.py`,
`apps/api/app/services/host_agent.py`, `external_backup_agent.py`,
`maintenance.py`.

Operational rules:

- Treat agent ports `8090`, `8091`, `8092` as restricted surfaces.
- Preserve `X-Agent-Token` authentication on all privileged HTTP actions.
- Assume disk preparation, partitioning, mounting, USB passthrough, and PBS
  datastore work are safety-critical.
- Confirm whether a change affects the Proxmox host agent, PBS agent, app
  maintenance agent, or all three.

Deployment wiring: `infra/docker/docker-compose.yml` (app VM stack),
`apps/agent/deploy/systemd/` (host/PBS agent services/timers),
`apps/app-maintenance-agent/deploy/systemd/` (app VM maintenance deployment),
`.env.example` (variable contract across app VM and agents).

Destructive code paths needing cautious review: anything calling mount, format,
wipe, `qm`, `parted`, `wipefs`, `sgdisk`, or `proxmox-backup-manager`. Do not
relax device filtering or destructive confirmations without checking the
operational docs and tests. Keep maintenance behavior explicit about git state,
`.env` preservation, and restart side effects.

Relevant tests: `apps/api/tests/test_proxmox_client.py`,
`test_external_backup_execution.py`, `test_disk_handoff.py`,
`apps/app-maintenance-agent/tests/test_env_preservation.py`,
`apps/agent/tests/test_external_export.py`.

For troubleshooting: start from the failing surface (app VM, Proxmox host
agent, PBS agent, or maintenance agent), trace the exact HTTP boundary and
token/env dependency before proposing a fix, and update matching docs when
deployment assumptions, ports, service names, or required env vars change.

## Deployment mechanics — what "Update All" actually does

Read `docs/MAINTENANCE.md` in full before telling a user their change is
"just a click away" — the update button's coverage differs per component, and
telling the user the wrong thing here has already caused a real production
incident (a live deployment kept running old, unauthenticated agent code for
hours because these gaps weren't obvious).

- **App VM** (web/api/db): fully automatic. `git pull` + `docker compose up
  --build -d` recreates the containers, and `create_tables()` applies
  additive DB schema changes on API startup.
- **Proxmox host agent / PBS agent**: `git pull --ff-only` in
  `AGENT_REPO_PATH`, then (if `AGENT_HTTP_SERVICE_NAME` is configured) a
  delayed self-restart of the agent's own `-http.service` — see
  `_maintenance_restart_http_service` in `apps/agent/src/agent/main.py`. This
  only works end-to-end if **both** of these hold on the target machine:
  1. `AGENT_REPO_PATH` points at a real git clone of this repo (not a
     directory populated by `scp`/`rsync` — that has no `.git`, so `git
     fetch`/`pull` fails silently and the agent keeps running whatever code
     was last copied there, no matter how many times the button is clicked).
  2. `AGENT_HTTP_SERVICE_NAME` is set to the actual systemd unit name for that
     machine's agent HTTP service. Without it, the pull can succeed while the
     long-running process still serves old code from memory.
- **App maintenance agent**: has its own equivalent self-restart, already
  wired (`_restart_agent_service` in
  `apps/app-maintenance-agent/src/app_maintenance_agent/main.py`).

Before claiming a change is fully deployed after "Update All": if the change
touches `apps/agent`, confirm the target machine actually satisfies both
conditions above (ask the user, or check `git status`/`.env` on that
machine) rather than assuming the button covered it.

**Never suggest a bare `docker compose -f infra/docker/docker-compose.yml
...` command for the App VM — always include `--env-file .env`.** Without it,
Compose resolves the `${VAR}` references inside the compose file's
`environment:` block using its own default env-file lookup next to the
compose file (`infra/docker/.env`, which doesn't exist), not the real `.env`
at the repo root — silently blanking settings like notifications even though
`env_file: ../../.env` loaded them correctly one line earlier in the same
file. This has already caused a real incident (ntfy config reverting to
defaults after a manual rebuild). `app-maintenance-agent`'s own update flow
already gets this right; a manually-typed command is where it goes wrong.

## Local development

```powershell
# API
cd apps/api
py -m venv .venv
.venv\Scripts\pip install -e .
.venv\Scripts\uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Web
cd apps/web
npm install
npm run dev

# Full stack via Docker Compose
Copy-Item .env.example .env
docker compose --env-file .env -f infra/docker/docker-compose.yml up --build

# Admin password hash
py scripts/generate_password_hash.py
```

The password-hash script prints a Compose-safe `AUTH_PASSWORD_HASH=...` line.
Keep the doubled `$` characters intact when copying into `.env` — Compose env
files need `$$` or the API receives a truncated hash and rejects login.

## Testing status (read before assuming coverage)

Existing tests: 10 files under `apps/api/tests/`, 1 under
`apps/agent/tests/` (`test_external_export.py`), 1 under
`apps/app-maintenance-agent/tests/` (`test_env_preservation.py`), 1 under
`apps/web/tests/` (`diskPlanning.test.ts`, written against Node's built-in
`node:test` but **not wired to any npm script** — run it directly with
`node --test` rather than assuming `npm run test` covers it).

No CI is configured (no `.github/workflows`). No e2e framework (no Playwright/
Cypress) exists for the web app. Several routes/services have no dedicated test
file — see `ROADMAP.md` for the list before claiming a change is "fully tested."

## Safety notes

- Dedicated PBS datastore preparation can format the selected disk. Treat it as
  destructive until proven otherwise.
- Do not expose ports `8090`, `8091`, `8092` broadly.
- Never commit `.env` or agent environment files.
- The agents execute host-local commands such as mount, partition, QEMU USB
  attach/detach, and `proxmox-backup-manager`. Read the relevant docs before
  changing those paths.
