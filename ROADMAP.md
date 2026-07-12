# Roadmap

Backlog of known gaps and planned work for Proxmox Backup Orchestrator, derived
from a source-level audit on 2026-07-12. This complements `AGENTS.md` (how to
work in the repo) — this file tracks **what** should be built or fixed next.

Any AI agent or contributor picking up work here should update the status of an
item when it changes, and add new dated entries when a new gap or feature idea
is identified. Do not commit/push changes to this file automatically — see the
hard rule in `AGENTS.md`.

Status legend: `Not started` / `In progress` / `Done`.

## 1. Reliability fixes

### 1.1 Auto-eject after successful backup, for any disk mode — Not started

**Problem.** Auto-eject exists today, but only in one narrow path:
`apps/api/app/services/planning_scheduler.py:386-392` ejects the disk after a
*scheduled* run succeeds, gated by `ScheduledBackupEvent.auto_eject_after_success`
(`apps/api/app/models/scheduled_backup.py:57`). Manual/on-demand runs started via
`POST /external-backups/run` → `execute_external_backup_run()`
(`apps/api/app/services/external_backups.py:220-359`) never call eject at all —
the operator must always click "Eject" by hand after a manual run.

On top of that, `eject_dedicated_external_disk()` and
`is_disk_auto_eject_eligible()` (`apps/api/app/services/disk_eject.py:25-37`)
only accept disks where `dedicated_backup_disk` or `prepared_as_pbs_datastore`
is true. A disk running in coexistence mode
(`ExternalBackupMode.COEXISTENCE`, `external_backups.py:43-48`) has **no eject
path at all**, manual or automatic — it only unmounts the dedicated PBS
datastore, not a generic mount point.

**Goal.** Auto-eject the disk after a successful backup event, regardless of
whether the disk is a dedicated PBS datastore or a coexistence/generic disk.

**Suggested approach:**

1. Add the same auto-eject call used in `planning_scheduler.py:386-392` to the
   success path of `execute_external_backup_run()` in `external_backups.py`
   (around the `run.status = BackupRunStatus.SUCCESS` block, ~line 308-325), so
   manual runs can auto-eject too. This likely needs a per-run flag (today only
   `ScheduledBackupEvent` carries `auto_eject_after_success`).
2. Extend `disk_eject.py` to support coexistence-mode disks: unmount the
   generic `pbs_mount_path` instead of assuming a dedicated datastore, and widen
   `is_disk_auto_eject_eligible()` accordingly.
3. Add regression tests: no existing test verifies that
   `eject_dedicated_external_disk` is actually invoked when
   `auto_eject_after_success=True` and the run succeeds — see
   `test_linked_backup_success_updates_planned_occurrence_success` in
   `apps/api/tests/test_planning_events.py:121-135`, which uses an event without
   that flag set. Add coverage for both the scheduled and manual paths, and for
   both dedicated and coexistence disks.

## 2. CI/CD — Not started

- No `.github/workflows` exists. Add a pipeline that at minimum lints and tests
  `apps/api`, `apps/agent`, `apps/app-maintenance-agent`, and `apps/web` on
  push/PR.
- Prerequisite: wire the placeholder `Makefile` targets (`install`, `dev`,
  `lint`, `test` are currently `@echo "... (placeholder)"`,
  `Makefile:6-16`) to real per-app commands so CI has one entry point per
  action instead of duplicating per-app invocations in the workflow file.

## 3. Tests / coverage — Not started

- `apps/web/tests/diskPlanning.test.ts` uses Node's built-in `node:test` but
  isn't wired to any `npm` script (`apps/web/package.json` has no `test`
  script and no test dependency). Add a `test` script (e.g.
  `node --test tests/`) so it actually runs somewhere other than manually.
- No test file exists for these API routes: `backup_runs.py`, `maintenance.py`,
  `agent.py`, `integrations_pbs.py`, `overview.py`, `vms.py`,
  `integrations_proxmox.py`, `proxmox.py`, `assets.py`, `system.py`,
  `health.py`.
- No test file exists for these services: `proxmox_sync.py`, `pbs_client.py`,
  `disk_preparation_agent.py`, `disk_preparations.py`, `sync_state.py`,
  `asset_ignores.py`, `overview.py`, `pbs_progress.py`, `host_agent.py`,
  `external_backup_agent.py`, `disks.py`, `maintenance.py`, `disk_identity.py`.
- No e2e framework for `apps/web` (no Playwright/Cypress). Once the auto-eject
  work above lands, an e2e golden-path test (detect disk → prepare → backup →
  eject) would catch regressions that unit tests miss.

## 4. Multi-user support — Not started

**Current state.** Auth is single-account by design
(`apps/api/app/auth.py` docstring: *"Single-user JWT authentication for local
PBO deployments."*): one `AUTH_USERNAME` / `AUTH_PASSWORD_HASH` pair from env
vars, no `users` table, no roles/permissions, and `get_current_user()` resolves
only a bare username string, not a user object.

**Scope of the change**, if/when this becomes a priority:

1. Add a `users` table (id, username, password_hash, role, active) with an
   Alembic migration.
2. Replace the env-based check in `login()` (`auth.py:116-141`) with a DB
   lookup.
3. Change `get_current_user()` to resolve a full user object instead of a
   string, and update every route depending on `CurrentUser` accordingly.
4. Decide whether role-based access control is needed (today any authenticated
   caller has full API access) and design it if so.
5. Build account administration (create/disable users) — nothing like this
   exists today.

Treat this as its own milestone/epic — it's a foundational auth change, not an
incremental patch, and it's a likely prerequisite for any future per-operator
audit trail.

## 5. Minor housekeeping

- `packages/types/` and `packages/utils/` are empty placeholders (`README.md` +
  `.gitkeep` only). Decide whether to actually use them for shared
  code/types across apps or remove them to avoid confusing future
  contributors/agents.
- `Makefile` targets `install`, `dev`, `lint`, `test` are placeholders — wire
  them as part of the CI/CD work in section 2.
