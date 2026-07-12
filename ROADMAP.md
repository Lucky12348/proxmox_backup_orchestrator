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

**Follow-up bug found during a real hardware test (2026-07-12), fixed same
day**: the very first end-to-end test (after fixing §1.2b below) hit a
genuine race condition, not the hardware limitation above —
`spin_down_disk_result` called `resolve_disk()` immediately after QEMU USB
detach, before the Proxmox host's kernel had finished re-enumerating the
physical device as a block device, so it raised `FileNotFoundError` every
time (`Unable to resolve disk from identifier: ...`). Fixed by
`_resolve_disk_after_usb_detach()`: run `udevadm settle --timeout=5` first,
then retry `resolve_disk()` up to 4 times with a 1s pause between attempts
before giving up. Covered by
`test_spin_down_waits_for_disk_to_reappear_after_usb_detach` in
`apps/agent/tests/test_external_export.py`.

**Paused — 2026-07-12, not urgent.** Re-tested after the race-condition fix:
the disk was resolved correctly this time and the agent reported
`"Disk spin-down/power-off attempted."` (i.e. at least one of `hdparm -y` /
`udisksctl power-off` returned success) — but the physical disk was still
spinning with its LED lit. Two things are still unknown and left for later:

1. `_attempt_disk_spin_down()` (`apps/api/app/services/disk_eject.py`) only
   surfaces the agent's one-line summary message into the run's activity
   log, not the per-tool `attempts` detail (each tool's own return code /
   stdout / stderr) that `spin_down_disk_result()` already returns. Logging
   that detail would show directly in the app which of the two commands
   "succeeded" and with what output, instead of requiring SSH + manual
   `hdparm`/`udisksctl` runs to diagnose.
2. Whether `udisksctl power-off` returning success on this hardware actually
   means anything (vs. a hub/port that silently no-ops) is still unverified.

Next time this is picked up: surface the detailed `attempts` array in the
activity log first (small, contained change), then re-test — that alone
should answer whether it's the known hardware limitation or something else,
without needing a manual SSH diagnostic session.

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

### 1.2b Both agents' `.venv` were editable-installed against an orphaned clone — Done — 2026-07-12

**Problem, found while debugging why a new capability (`disk-spin-down`,
§1.1b) still 404'd after 1.2's git-conversion was verified working.** Both
`/opt/proxmox-backup-orchestrator-agent/.venv` and
`/opt/proxmox-backup-orchestrator-pbs-agent/.venv` had been created with
`pip install -e .` run against `/opt/proxmox_backup_orchestrator` — a
complete, separate monorepo clone that exists on **both** the Proxmox host
and the PBS VM, unrelated to (and predating) the `-agent`/`-pbs-agent`
directories this project's docs assume. Editable installs record an absolute
path at install time (`__editable__.proxmox_backup_orchestrator_agent-*.pth`
in the venv's `site-packages`); that path pointed at the orphaned clone, so
**every** git-pull-based update this session (§1.1b, §1.2's own conversion)
was silently invisible to the actually-running process — `git_sha` and
`systemctl` restart timestamps looked current, but `installed_path` in
`GET /version` revealed the process was really loading
`/opt/proxmox_backup_orchestrator/apps/agent/src/agent/main.py`.

**Fix**: `pip install -e . --force-reinstall --no-deps` run from each of
`/opt/proxmox-backup-orchestrator-agent` and `-pbs-agent` (with `src`/`tests`
already symlinked into the real `-repo` clone per §1.2), then a manual
service restart. Verified via `GET /version` → `installed_path` and
`capabilities` on both machines. **Diagnostic takeaway for next time**: don't
trust `git_sha` or restart timestamps alone to prove new code is live —
`installed_path` in the `/version` response is the one field that reflects
what the running process actually resolved `__file__` to.

**Still open**: the orphaned `/opt/proxmox_backup_orchestrator` clones on
both machines are unused now but still present — safe to remove once
confident nothing else references them (nothing found so far), not urgent.

### 1.3 Manual `docker compose` commands silently blank out `.env` settings — Done — 2026-07-12

**Problem, raised by the user.** Notifications (ntfy) config kept reverting
to defaults after rebuilding the App VM stack manually. Root cause: the `api`
service in `infra/docker/docker-compose.yml` declares both `env_file: -
../../.env` (loads the real `.env`) **and** an `environment:` block that
re-references some of the same variables as `${VAR}` (e.g.
`NOTIFICATIONS_ENABLED`, `NTFY_BASE_URL`, `NTFY_TOPIC`). Compose resolves
those `${VAR}` references using its *own* env-file lookup — by default a
`.env` next to the compose file (`infra/docker/.env`, which doesn't exist) —
independent of the service's `env_file:` directive. Without `--env-file .env`
passed to the `docker compose` command itself, those references resolve to
empty strings and **overwrite** the correct values `env_file:` just loaded,
one block earlier in the same file. Every documented manual command
(`README.md`, `AGENTS.md`, `docs/setup.md`, `docs/OPERATIONS.md`,
`docs/INSTALLATION.md`, `Makefile` `up`/`down` targets) was missing this flag
— only the automated `app-maintenance-agent` update flow got it right.

**Fix.** Added `--env-file .env` to every documented/scripted
`docker compose -f infra/docker/docker-compose.yml ...` invocation across the
7 files above. `AGENTS.md` now has an explicit warning in the "Deployment
mechanics" section so no AI agent suggests the bare command again.

**Considered and rejected:** moving ntfy config into the database (in
addition to env), so the operator could edit it from the UI. Rejected because
it treats a symptom, not the cause — the same missing-flag bug would still
silently blank out *any* other env-based setting (Proxmox/PBS API tokens,
`AUTH_SECRET_KEY`, agent tokens...) on a manual rebuild; fixing the actual
deployment commands closes the gap for all of them at once. The existing
`NotificationPreferences` DB-override mechanism already lets an operator
toggle individual notification *events* from the UI — a fuller "ntfy
server/credentials in DB" mode remains a legitimate but separate, larger
feature if wanted later (secrets-at-rest handling, a settings-edit UI, merge
precedence with env) rather than a fix for this incident.

### 1.4 Updating a Proxmox backup job's VM selection could 400 — Done — 2026-07-12

**Problem, raised by the user.** Adding/removing a VM from an existing
Proxmox backup job (Assets page → "Gerer la selection") failed with
`Proxmox API rejected update: Client error '400 Parameter verification
failed'` on jobs configured with more than one `keep-*` retention rule.

**Root cause**: the same dict-vs-string quirk as the `retention` display bug
(§ elsewhere this session) — `ProxmoxClient.update_backup_job_selection()`
(`apps/api/app/services/proxmox_client.py`) round-trips every field from a
`GET` straight into the `PUT` body. When `prune-backups` has more than one
rule, Proxmox returns it as a dict on `GET` (e.g. `{"keep-last": "4",
"keep-monthly": "8"}`); sending that dict back verbatim in a form-encoded
`PUT` body is what Proxmox rejects.

**Fix**: extracted the flattening logic into a shared
`flatten_pve_property_value()` (`proxmox_client.py`), used both by
`update_backup_job_selection()` before sending and by the existing
`_format_retention()` (`apps/api/app/api/routes/proxmox.py`) for display —
one function, one bug class closed for both read and write paths. Covered by
`test_update_backup_job_selection_flattens_multi_rule_retention` and the
`FlattenPveScalarPropertyValueTests` suite in `apps/api/tests/`.

### 1.5 Proxmox backup job management: create/delete from the app — Done (MVP scope) — 2026-07-12

Requested by the user after fixing §1.4: manage Proxmox backup jobs (the
`Datacenter → Backup` jobs feeding PBS) directly from the Assets page instead
of only being able to tweak VM selection on jobs created in Proxmox itself.

**Scope, deliberately limited (user's choice)**: node, storage, schedule,
mode, enabled/comment, a simple `keep-*` retention (last/daily/weekly/monthly/
yearly counts), and VM/CT selection. **Not** covered — matches Proxmox's own
"Notifications" / "Note Template" / "Advanced" tabs; use the Proxmox UI
directly for those.

**Backend**: `ProxmoxBackupJobUpsert` schema
(`apps/api/app/schemas/integrations_proxmox.py`); `create_backup_job` /
`replace_backup_job` / `delete_backup_job` on `ProxmoxClient`
(`proxmox_client.py`); `POST` / `PUT` / `DELETE /proxmox/backup-jobs[/{id}]`
routes (`apps/api/app/api/routes/proxmox.py`). Unlike the existing
selection-update endpoint, create/replace send **only** the fields the form
actually exposes (no round-tripping unknown fields from `GET`) — simpler and
avoids reintroducing bugs like §1.4 for fields outside this MVP's scope.
`POST /cluster/backup`'s response doesn't reliably carry the new job's id
across PVE versions, so the created job is located afterwards by matching
schedule/storage/vmid (`_find_job_by_signature`) — fragile if two jobs share
an identical signature, acceptable for a single-operator home lab.

**Frontend**: new create/edit modal on the Assets page
(`apps/web/src/pages/AssetsPage.tsx`) reusing the existing VM-selection grid
styling; "+ Nouveau job", "Modifier", "Supprimer" actions per job card.
Deliberately kept the surrounding hardcoded-French strings instead of adding
`i18n` keys, matching this section's existing (already non-i18n'd) style.

**Tests**: `apps/api/tests/test_proxmox_backup_jobs.py` (payload building,
retention parsing, job-signature matching) and
`apps/api/tests/test_proxmox_client.py` (client method wiring). No test
exercises the new routes end-to-end through FastAPI's dependency injection —
same pre-existing gap as the rest of `proxmox.py` (see §3).

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
  `integrations_proxmox.py`, `assets.py`, `system.py`, `health.py`.
  (`proxmox.py` now has partial coverage — see §1.4 — but only for the pure
  helper functions, not the routes themselves end-to-end.)
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
