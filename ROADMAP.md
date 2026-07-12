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

### 1.1 Auto-eject after successful backup, for any disk mode — Partially done — 2026-07-12

**Done.** Manual/on-demand runs can now auto-eject too, opt-in per run (not a
silent default): `POST /external-backups/run` accepts
`auto_eject_after_success` (`apps/api/app/schemas/external_backup.py`), stored
on `ExternalBackupRun` (new column, `apps/api/app/models/external_backup_run.py`
+ `apps/api/app/db/init.py`). `execute_external_backup_run()`'s success path
(`apps/api/app/services/external_backups.py`) calls
`eject_dedicated_external_disk()` when the flag is set, mirroring the existing
scheduled-run path in `planning_scheduler.py:386-392` — failures are logged to
the run's activity log rather than failing the (already-successful) backup.
The web UI exposes this as a checkbox (checked by default) in the "Lancer une
sauvegarde externe" confirmation modal (`apps/web/src/App.tsx`,
`ConfirmModal.tsx`). Covered by `apps/api/tests/test_auto_eject.py`.

**Still open — coexistence-mode disks still can't be ejected at all, manual
or automatic.** `eject_dedicated_external_disk()` and
`is_disk_auto_eject_eligible()` (`apps/api/app/services/disk_eject.py:25-37`)
only accept disks where `dedicated_backup_disk` or `prepared_as_pbs_datastore`
is true. A disk running in coexistence mode
(`ExternalBackupMode.COEXISTENCE`, `external_backups.py:43-48`) has **no eject
path at all** — it only unmounts the dedicated PBS datastore, not a generic
mount point. Checking the new checkbox for a coexistence disk today just logs
"this disk mode does not support it yet" instead of ejecting. To close this:

1. Extend `disk_eject.py` to support coexistence-mode disks: unmount the
   generic `pbs_mount_path` instead of assuming a dedicated datastore, and
   widen `is_disk_auto_eject_eligible()` accordingly.
2. Add regression tests for the scheduled-run path specifically: no existing
   test verifies that `eject_dedicated_external_disk` is invoked when
   `ScheduledBackupEvent.auto_eject_after_success=True` and the run succeeds —
   see `test_linked_backup_success_updates_planned_occurrence_success` in
   `apps/api/tests/test_planning_events.py:121-135`, which uses an event
   without that flag set.

### 1.1b Eject doesn't power down the physical disk — Done (best-effort) — 2026-07-12

**Problem, raised by the user.** After ejecting a disk, its LED stays on and
it keeps spinning — unlike Windows' "safely remove hardware." Confirmed by
code audit: the eject flow only unmounts the filesystem
(`eject_dedicated_pbs_datastore_result` on the PBS agent) and removes the QEMU
USB passthrough config (`qemu_usb_detach_result`, `qm set <vmid> -delete
<slot>`, `apps/agent/src/agent/main.py`). Nothing anywhere in the codebase
ever asked the host to power down or spin down the drive.

**Fix.** New best-effort step after USB detach: the host agent's
`spin_down_disk_result()` (`apps/agent/src/agent/main.py`) resolves the
physical device and tries, in order, `hdparm -y` (ATA standby) then
`udisksctl power-off -b` (USB port power-off), each independently optional —
missing tools or hardware that doesn't support them are logged, never fail
the eject. Wired in from `apps/api/app/services/disk_eject.py`
(`_attempt_disk_spin_down`) via a new `POST /disk/spin-down` agent endpoint.
Covered by `apps/agent/tests/test_external_export.py` (spin-down cases) and
`apps/api/tests/test_auto_eject.py` (API-side wiring).

**Known limitation, not fixable in software**: many onboard motherboard
USB root-hub ports don't support per-port power switching, so `udisksctl
power-off` can silently do nothing on that hardware, and the LED — often just
wired to USB 5V presence — stays lit until the cable is physically unplugged
regardless of what runs on the host. `hdparm -y` still stops the platters
spinning on drives that honor ATA standby over their USB-SATA bridge, even
when the LED itself can't be controlled.

### 1.2 Agent updates don't reach the Proxmox host / PBS VM — Done — 2026-07-12

**Problem, discovered live in production.** A security fix to
`apps/agent/src/agent/main.py` was pushed and "Tout mettre à jour" reported
success, but the running host and PBS agents kept executing the old code for
hours (visible as a repeated 401 loop on the periodic heartbeat job). Root
cause, confirmed on the actual servers: `AGENT_REPO_PATH`
(`/opt/proxmox-backup-orchestrator-agent` and `-pbs-agent`) were plain
directories populated by manual file copies, not git checkouts — `git
fetch`/`pull` in the maintenance flow had nothing to do. Separately, even a
real `git pull` would not have reloaded the running `-http.service` process,
since nothing restarted it.

**Fix shipped in code** (`apps/agent/src/agent/main.py`,
`maintenance_update_result` / `_maintenance_restart_http_service*`,
2026-07-12): after a successful `git pull --ff-only`, the agent now schedules
a delayed self-restart of its own HTTP service via `systemd-run
--on-active=10 ... systemctl restart <AGENT_HTTP_SERVICE_NAME>` (falling back
to `systemctl try-restart ... --no-block`) — the same pattern
`apps/app-maintenance-agent` already used for itself. New setting:
`AGENT_HTTP_SERVICE_NAME` (see `.env.example`, `docs/MAINTENANCE.md`).
Covered by `apps/agent/tests/test_maintenance.py`.

**One-time manual setup completed on both machines (2026-07-12):** both
`/opt/proxmox-backup-orchestrator-agent` and `-pbs-agent` now have a sibling
`-repo/` full git clone (public repo, HTTPS), with `src/`/`tests/` replaced by
symlinks into `<repo>/apps/agent/{src,tests}`, and `AGENT_REPO_PATH` /
`AGENT_HTTP_SERVICE_NAME` set in each `.env`. Verified via
`POST /maintenance/check` on both agents: `status: up_to_date`, matching
local/remote commit. The actual pull-then-self-restart path (as opposed to
just git status resolving) will get its first real exercise on the next push
that changes `apps/agent` — worth a quick check the first time it happens.

**Still open / minor follow-ups:**

- The shipped systemd unit filenames in
  `apps/agent/deploy/systemd/*-api.service` don't match the real installed
  unit names on this deployment (`*-http.service`) — reconcile these so a
  fresh install doesn't silently diverge from what's actually running.
- `src.bak` / `tests.bak` (and an older `.venv.bak-after-pve9-*` found on the
  Proxmox host) are harmless leftovers from this migration and the previous
  PVE upgrade; safe to delete once confident, not urgent.

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
