---
name: project-orientation
description: Understand and navigate the proxmox_backup_orchestrator monorepo. Use when an agent needs a fast map of the repository, needs to find the correct app or entrypoint to modify, or needs to know which docs to read first before changing API, web, agent, maintenance, or infrastructure code.
---

# Project Orientation

Start by reading `README.md`. Use it as the top-level map, then go directly to the relevant app or doc instead of scanning the entire repository.

Use this repository map:

- Read `apps/api` for FastAPI routes, services, models, schemas, auth, and orchestration logic.
- Read `apps/web` for React pages, UI components, hooks, and frontend API calls.
- Read `apps/agent` for root-capable host and PBS agent behavior.
- Read `apps/app-maintenance-agent` for app-VM git and Docker Compose maintenance endpoints.
- Read `infra/docker/docker-compose.yml` and `infra/docker/*.Dockerfile` for deployed app-stack wiring.
- Read `docs/*.md` for production behavior, security assumptions, and operator workflows.

Use these likely entrypoints first:

- `apps/api/app/main.py`
- `apps/api/app/api/router.py`
- `apps/web/src/App.tsx`
- `apps/agent/src/agent/main.py`
- `apps/agent/src/agent/server.py`
- `apps/app-maintenance-agent/src/app_maintenance_agent/main.py`

Route yourself by task:

- Open `apps/api/app/api/routes/` when the request mentions endpoints, auth, UI data, or API regressions.
- Open `apps/api/app/services/` when the request mentions business rules, orchestration, planning, sync, notifications, disk handling, or external backups.
- Open `apps/api/app/models/` and `apps/api/app/schemas/` when persistence or response shape changes are involved.
- Open `apps/web/src/pages/` when the request is screen-oriented.
- Open `apps/web/src/components/` and `apps/web/src/api.ts` when the request is frontend behavior or data fetching.
- Open `apps/agent` when the request touches disk discovery, USB passthrough, datastore preparation, export execution, or safe eject.
- Open `docs/INSTALLATION.md`, `docs/OPERATIONS.md`, and `docs/SECURITY.md` before modifying deployment or privileged flows.

Prefer targeted search over broad reading:

- Use `rg "symbol-or-endpoint"` from the repo root.
- Search route names in `apps/api/app/api/routes`.
- Search service names in `apps/api/app/services`.
- Search page names in `apps/web/src/pages`.

Treat the source of truth as layered:

1. Runtime behavior in code.
2. `README.md` for repo-level orientation.
3. `docs/*.md` for operator and deployment expectations.

Do not assume the generic run targets in `Makefile` are complete. Verify per-app commands in each app README or pyproject/package file before proposing execution steps.
