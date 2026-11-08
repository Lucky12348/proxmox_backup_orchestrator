# Agent

Minimal Python scaffold intended to run on either a Proxmox host or a PBS host.

## Current scope

This phase does not implement hotplug watching yet. It provides:

- heartbeat reporting to the backend
- real disk report submission using Linux host inspection
- one-shot state sync combining heartbeat and real disk report
- an authenticated HTTP API for host-side disk preparation and PBS-side export actions
- an authenticated HTTP API for disk inspection used during Proxmox-to-PBS handoff checks
- target-directory preparation for an external datastore path
- disk inspection and application-managed preparation commands
- a real PBS-native-like external export command boundary when host dependencies are present
- optional mock disk report submission for development
- a simple CLI contract for future host-side integration
- (Proxmox host role) management of the host's file-driven ntfy notification engine:
  `GET`/`PUT /notifications/templates`, `POST /notifications/test`,
  `GET /notifications/history`, `GET /notifications/queue` — see
  `docs/NOTIFICATIONS.md` § "Host notification engine". Code in
  `src/agent/ntfy_notif.py`; it never reads `/etc/ntfy-notif/ntfy.conf` (ntfy token).

## Environment

- `AGENT_API_BASE_URL`
- `AGENT_HOSTNAME`
- `AGENT_VERSION`
- `AGENT_TIMEOUT_SECONDS`
- `AGENT_INCLUDE_NON_USB_CANDIDATES`
- `AGENT_SERVER_HOST`
- `AGENT_SERVER_PORT`
- `AGENT_SERVER_TOKEN`
- `PBS_API_URL`
- `PBS_TOKEN_ID`
- `PBS_TOKEN_SECRET`
- `PBS_FINGERPRINT`
- `PBS_DATASTORE` (PBS agent role) — see "Source datastore" below
- `AGENT_EXPORT_TIMEOUT_SECONDS`
- `AGENT_EJECT_SYNC_TIMEOUT_SECONDS` (PBS agent role, default `1800`) — see "Safe eject" below
- Optional, Proxmox host role only (defaults match the standard host install):
  `NTFY_NOTIF_TEMPLATES_PATH` (`/etc/ntfy-notif/templates.json`),
  `NTFY_NOTIF_BACKUPS_DIR` (`/etc/ntfy-notif/backups`),
  `NTFY_NOTIF_HISTORY_PATH` (`/var/log/ntfy-notif/history.jsonl`),
  `NTFY_NOTIF_QUEUE_DIR` (`/var/spool/ntfy-queue`),
  `NTFY_NOTIF_SEND_COMMAND` (`/usr/local/bin/ntfy-send`)

## Run locally

1. Create a virtual environment.
2. Install the package with `pip install -e .`
3. Send a heartbeat with `python -m agent.main heartbeat`
4. Send a real disk report with `python -m agent.main report-disks`
5. Send both heartbeat and disk report with `python -m agent.main sync-state`
6. Optionally send a mock disk report with `python -m agent.main report-mock-disks`
7. Prepare an external datastore target with `python -m agent.main prepare-external-datastore --mount-path /mnt/backup --target-path /mnt/backup/pbs-datastore --mode dedicated`
8. Exercise the export boundary with `python -m agent.main run-external-export --target-path /mnt/backup/pbs-datastore --datastore-name backup --mode dedicated`
9. Inspect a disk with `python -m agent.main inspect-disk --disk <serial-or-path>`
10. Prepare a disk with `python -m agent.main prepare-disk --disk <serial-or-path> --mode preserve_existing_data`
11. Start the HTTP API with `python -m agent.main serve`
## Source datastore (`PBS_DATASTORE`)

`PBS_DATASTORE` must be the exact name of the existing PBS datastore that
exports copy **from** (your main datastore, whatever you named it — list them
with `proxmox-backup-manager datastore list`). The agent never assumes a name.

At startup the PBS agent checks that this datastore really exists on the PBS
and logs an error otherwise, e.g.
`Le datastore source X n'existe pas sur ce PBS ; datastores disponibles : …`.
The result is exposed in `GET /health` under `source_datastore`
(`status`: `ok`, `missing`, `not_configured`, `unavailable`, or
`not_applicable` on the Proxmox host where PBS is not installed), so the
orchestrator can surface the problem before a scheduled backup instead of
failing at export time.

> **If you rename or migrate your datastore**, update `PBS_DATASTORE` in the
> agent's `.env`, then restart the agent HTTP service, e.g.
> `systemctl restart proxmox-backup-orchestrator-pbs-agent-http.service`
> (use the unit name you installed; see `docs/INSTALLATION.md`).
> Update `PBS_DATASTORE` in the app VM `.env` too.

### Format protection

Before any destructive step (`wipefs`, `sgdisk`, `parted`, `mkfs`), the agent
reads **all** PBS datastores (`proxmox-backup-manager datastore list`) and
refuses to format a disk if the disk, one of its partitions or one of its
mounts holds any of them (by path, by the device backing the datastore path,
or by `backing-device` for PBS removable datastores). It also refuses any
disk mounted at, under or above `/mnt/datastore`, plus `/`, `/boot`,
`/boot/efi` and system (LVM/ZFS) disks. If PBS is installed but the datastore
list cannot be read, formatting is refused (fail closed).

## Safe eject (`AGENT_EJECT_SYNC_TIMEOUT_SECONDS`)

Before unmounting a dedicated datastore disk, the PBS agent flushes that disk's
filesystem with `sync -f <mount point>` and waits up to
`AGENT_EJECT_SYNC_TIMEOUT_SECONDS` (default `1800`). After a large export,
writing the cached data to a USB disk can take several minutes.

While it waits, the agent logs `Dirty` and `Writeback` from `/proc/meminfo`
every 15 seconds (system-wide values) and streams them to the eject run, so
the Activity page shows that writing is still in progress.

If the timeout is reached anyway, the agent does **not** unmount the
datastore, and the orchestrator does **not** detach the disk from the PBS VM.
The run ends with the state "Éjection non terminée … NE PAS débrancher le
disque" (shown in the UI and sent as a high-priority ntfy alert), and a
**Retry eject** button appears on that run in the Activity page. Keep this
value below the app VM's `PBS_AGENT_TIMEOUT_SECONDS` (default `7200`), which
bounds the whole eject request.

## Deployment roles

The same agent app is deployed in two pragmatic roles:

- Proxmox host agent:
  disk detection, heartbeat/report sync, disk preparation, mount-path handling,
  host ntfy notification templates/history/queue (`/notifications/*`). Saving
  templates requires the HTTP service to run as root (`User=root`): it rewrites
  `/etc/ntfy-notif/templates.json` as `root:nut` `0664` and keeps backups in
  `/etc/ntfy-notif/backups/`. A non-root agent gets an explicit 403 instead of a workaround.
- PBS execution agent:
  PBS-native export execution through `proxmox-backup-manager`

The HTTP surface can be the same on both, but the backend now uses different base URLs and tokens for each responsibility.
For PBS-native export, the backend also asks Proxmox to pass the detected USB disk through to the PBS VM, then verifies visibility on PBS via the `/inspect-disk` endpoint.

## Systemd deployment

Deployable systemd examples are in `deploy/systemd/`.

The examples assume:

- the agent project is copied to `/opt/proxmox-backup-orchestrator-agent`
- the virtual environment lives at `/opt/proxmox-backup-orchestrator-agent/.venv`
- runtime environment variables are stored in `/opt/proxmox-backup-orchestrator-agent/.env`

On the Proxmox host, the deployment has two systemd responsibilities:

- `proxmox-backup-orchestrator-agent-api.service` runs the long-lived HTTP API
- `proxmox-backup-orchestrator-agent.service` remains a one-shot sync job for heartbeat and disk reporting
- `proxmox-backup-orchestrator-agent.timer` triggers that sync job every 2 minutes

On the PBS host, deploy the same app with:

- `proxmox-backup-orchestrator-pbs-agent-api.service`

When the backend triggers host-side commands, it calls the Proxmox host agent API with:

- `HOST_AGENT_BASE_URL=http://proxmox-host:8081`
- `HOST_AGENT_TOKEN=...`

For PBS-native export execution, the backend calls the PBS agent API with:

- `PBS_AGENT_BASE_URL=http://pbs-host:8081`
- `PBS_AGENT_TOKEN=...`

The `serve` command reads:

- `AGENT_SERVER_HOST`
- `AGENT_SERVER_PORT`
- `AGENT_SERVER_TOKEN`

## Real discovery heuristics

The real disk report uses `lsblk -J` and optional `udevadm info`.

Current filtering is intentionally pragmatic:

- only `TYPE=disk`
- exclude `loop`, `dm-*`, `zd*`, and `sr*`
- exclude disks backing the host system and obvious Proxmox storage members
- report only disks that are clearly external or removable by default
- examples include `TRAN=usb`, `RM=1`, `HOTPLUG=1`, `ID_BUS=usb`, and USB-related udev properties
- exclude internal SATA or ATA disks by default, even if they look unused

If you really need the older advanced behavior, set:

- `AGENT_INCLUDE_NON_USB_CANDIDATES=true`

That allows standalone non-system physical disks again, but the default remains strict and safe.

If a filesystem or mount point exists on a partition, the agent derives it from child partitions instead of requiring it on the parent disk node.

For PBS-native export execution, the PBS host also needs `proxmox-backup-manager` in `PATH`.
The command flow creates a target datastore on the removable media, creates a temporary
remote and sync job, runs the sync, and returns structured stdout/stderr logs.
